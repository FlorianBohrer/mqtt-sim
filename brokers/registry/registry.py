"""Lab registry for the EMQX HTTP authenticator (ENTC-63 R06, R11). Lab prototype, not for production.

EMQX calls POST /auth for every CONNECT with the certificate CN (= username) and the Client ID.
The registry allows the connection only when
  1. the certificate has a CN that belongs to the fleet (synthetic/fleet.json),
  2. the Client ID is the one authorised for that CN (credential -> serial -> Client ID, R06), and
  3. no connection with this Client ID is open (EMQX REST API, R11). A reconnect after a dropped
     link gets DUPLICATE_GRACE_S seconds for the broker to notice the old connection is gone; a
     second live connection is rejected and the first one keeps working.
Anything it cannot decide (unknown CN, API error) is rejected: fail closed.

Environment: FLEET (path to fleet.json), EMQX_API (e.g. http://emqx-registry:18083/api/v5),
EMQX_API_KEY_FILE (one line "key:secret", see api_key.bootstrap_file), DUPLICATE_GRACE_S, PORT.
Standard library only, so it runs in the plain python:3.12-alpine image without pip.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def authorised_ids(fleet):
    """Certificate CN -> the one Client ID it may use (gateways and cloud services)."""
    allowed = {g['certificate_cn']: g['client_id'] for g in fleet.get('gateways', []) if g.get('certificate_cn')}
    allowed.update({s['identity']: s.get('client_id', s['identity']) for s in fleet.get('services', [])})
    return allowed


def decide(allowed, cn, client_id, is_connected, grace_s=3.0, sleep=time.sleep, clock=time.monotonic):
    """('allow' | 'deny', reason). is_connected(client_id) -> bool, raises when the broker cannot answer."""
    if not cn:
        return 'deny', 'certificate without CN'
    expected = allowed.get(cn)
    if expected is None:
        return 'deny', f'CN {cn} is not in the fleet'
    if client_id != expected:
        return 'deny', f'Client ID {client_id} is not the one authorised for {cn} ({expected})'
    deadline = clock() + grace_s
    while is_connected(client_id):
        if clock() >= deadline:
            return 'deny', f'Client ID {client_id} is already connected'
        sleep(0.2)
    return 'allow', 'authorised Client ID, no other connection'


def emqx_connected(api, key):
    auth = 'Basic ' + base64.b64encode(key.encode()).decode()

    def is_connected(client_id):
        url = f"{api}/clients/{urllib.parse.quote(client_id, safe='')}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': auth}), timeout=3) as r:
                return json.load(r).get('connected') is True
        except urllib.error.HTTPError as e:
            if e.code == 404:   # no session and no connection with this Client ID
                return False
            raise
    return is_connected


def serve(allowed, is_connected, grace_s, port):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/auth':
                self.send_error(404)
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                cn, client_id = str(body.get('cn') or body.get('username') or ''), str(body.get('clientid') or '')
                result, reason = decide(allowed, cn, client_id, is_connected, grace_s)
            except Exception as e:   # fail closed
                cn, client_id, result, reason = '?', '?', 'deny', f'registry error: {type(e).__name__}: {e}'
            stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
            # Client ID and CN come from the client: JSON-quoted, so a line break cannot forge a log line
            print(f'{stamp} registry {result} cn={json.dumps(cn)} clientid={json.dumps(client_id)} '
                  f'reason={json.dumps(reason)}', flush=True)
            data = json.dumps({'result': result, 'is_superuser': False}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):   # one line per decision is enough
            pass

    print(f'registry listening on :{port} ({len(allowed)} identities)', flush=True)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()


def main():
    with open(os.environ.get('FLEET', '/lab/synthetic/fleet.json')) as fh:
        allowed = authorised_ids(json.load(fh))
    with open(os.environ['EMQX_API_KEY_FILE']) as fh:
        key = fh.readline().strip()
    serve(allowed, emqx_connected(os.environ['EMQX_API'], key),
          float(os.environ.get('DUPLICATE_GRACE_S', '3')), int(os.environ.get('PORT', '8080')))


if __name__ == '__main__':
    sys.exit(main())
