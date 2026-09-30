"""ENTC-63 acceptance harness: broker-agnostic MQTT security and session tests.

Every case runs against the broker described by a target profile (sim/targets/*.toml)
with the synthetic fleet's certificates. Payloads are opaque random bytes; no
application payload is decoded. Each case yields PASS / FAIL / PARTIAL (blocked in
effect, but not signalled as required) / INCONCLUSIVE, with the observation as
evidence. Phase `run` executes the MQTT cases, phase `report` adds the broker-log
checks, aggregates per ENTC-63 requirement and exits 0 only if every mandatory
case passed. Timeouts or missing answers never count as PASS.
"""
import hashlib
import json
import os
import random
import re
import socket
import ssl
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from .config import gateway_base, write_json, write_jsonl
from .mqttclient import Recorder, connect_properties, identity_files, new_client, wait_until

UNKNOWN_GATEWAY = 'gw-sim-900001'  # certs/negative/unknown-gateway (script 12)
ACCEPTED_CODES = (0, 16)           # PUBACK: success / success without matching subscriber
VERDICTS = ('PASS', 'FAIL', 'PARTIAL', 'INCONCLUSIVE')

REQUIREMENTS = [
    ('R01', 'mTLS with an individual X.509 certificate per simulated gateway'),
    ('R02', 'Connection without client certificate is rejected'),
    ('R03', 'Certificate signed by an untrusted CA is rejected'),
    ('R04', 'Invalid certificates (validity, key usage, revocation) are rejected'),
    ('R05', 'Certificate identity is bound to the Gateway ID (authorization follows the certificate)'),
    ('R06', 'MQTT Client ID = Gateway ID is enforced (otherwise the broker limitation is documented)'),
    ('R07', 'ACLs deny by default'),
    ('R08', 'A gateway publishes only to its own d2c namespace'),
    ('R09', 'A gateway subscribes only to its own c2d namespace'),
    ('R10', 'Cross-plant and cross-gateway topic access is denied'),
    ('R11', 'A duplicate Client ID does not silently take over the active session'),
    ('R12', 'QoS 1: acknowledged, at-least-once delivery incl. redelivery after connection loss'),
    ('R13', 'Clean Start = false resumes the persistent session across disconnect/reconnect'),
    ('R14', 'Reconnect can be exercised without a reconnect storm'),
    ('R15', 'Security-relevant broker logs are available and contain no keys or credentials'),
]


# Broker-neutral explanation shown in the report when a case does not PASS.
FINDINGS = {
    'MTLS-08': 'No revocation check is active (CRL, OCSP or registry lookup). Revocation strategy is OPEN '
               '(ENTC-58/ENTC-31); for Mosquitto `crlfile certs/negative/crl.pem` makes this case pass.',
    'ID-01': 'The broker accepts a Client ID that differs from the certificate identity and lets it displace the '
             'legitimate session. EICP v1.4 requires Client ID == Gateway ID; enforcement must come from the broker '
             '(classify NATIVE / CONFIGURATION / PLUGIN / CUSTOM for ENTC-59).',
    'DUP-01': 'The broker applies the MQTT session takeover. ENETEC requires rejecting the second connection and '
              'keeping the active session (ENETEC.md §6.3); needs broker support or an extension.',
    'SUBSCRIBE': 'The broker grants the SUBSCRIBE (SUBACK < 128) and filters on delivery: isolation holds, but the '
                 'denial is not signalled to the client and a denied subscription is not visible as such.',
}


class Inconclusive(Exception):
    """The case could not produce evidence either way (setup or positive control failed)."""


@dataclass
class Case:
    id: str
    requirement: str
    title: str
    expected: str
    mandatory: bool
    fn: object


CASES = []


def case(case_id, requirement, title, expected, mandatory=True):
    def register(fn):
        CASES.append(Case(case_id, requirement, title, expected, mandatory, fn))
        return fn
    return register


# --------------------------------------------------------------------------- clients

class ProbeClient:
    """One MQTT 5 connection on a paho network thread; every observation is logged."""

    def __init__(self, harness, label, client_id, files):
        self.h, self.label = harness, label
        certfile, keyfile = files if files else (None, None)
        self.client = new_client(client_id, harness.broker, certfile, keyfile)
        for name in ('connect', 'disconnect', 'publish', 'subscribe', 'message', 'log'):
            setattr(self.client, f'on_{name}', getattr(self, f'_on_{name}'))
        self.connack = self.session_present = None
        self.closed, self.acks, self.subacks, self.errors, self.messages = [], {}, {}, [], []
        self.cleanup = False

    def _log(self, event, **data):
        self.h.rec(self.label, event, **data)

    def _on_connect(self, client, userdata, flags, reason, props):
        self.connack, self.session_present = reason.value, bool(flags.session_present)
        self._log('connack', code=reason.value, reason=str(reason), session_present=self.session_present)

    def _on_disconnect(self, client, userdata, flags, reason, props):
        item = {'code': reason.value, 'reason': str(reason),
                'server_packet': flags.is_disconnect_packet_from_server, 'cleanup': self.cleanup}
        self.closed.append(item)
        self._log('connection_closed', **item)

    def _on_publish(self, client, userdata, mid, reason, props):
        self.acks[mid] = reason.value
        self._log('puback', mid=mid, code=reason.value)

    def _on_subscribe(self, client, userdata, mid, reasons, props):
        self.subacks[mid] = [r.value for r in reasons]
        self._log('suback', mid=mid, codes=self.subacks[mid])

    def _on_message(self, client, userdata, msg):
        self.messages.append(msg.payload)
        self._log('message_received', topic=msg.topic, qos=msg.qos, dup=bool(msg.dup),
                  retain=bool(msg.retain), payload_sha256=hashlib.sha256(msg.payload).hexdigest()[:16])

    def _on_log(self, client, userdata, level, text):
        if level in (mqtt.MQTT_LOG_ERR, mqtt.MQTT_LOG_WARNING):
            self.errors.append(text)
            self._log('client_log', text=text)

    def open(self, clean_start=True, session_expiry=None, timeout=6):
        """Returns (ACCEPTED | REJECTED | UNREACHABLE | NO_RESPONSE, detail).

        Only a TLS alert, a CONNACK >= 128 or a close before CONNACK is a rejection.
        An unreachable broker is never evidence for rejecting a certificate."""
        props = connect_properties(session_expiry) if session_expiry is not None else None
        try:
            self.client.connect(self.h.broker.host, self.h.broker.port, keepalive=30,
                                clean_start=clean_start, properties=props)
        except ssl.SSLError as exc:
            detail = f'{type(exc).__name__}: {exc}'
            self._log('connect_error', error=detail)
            return 'REJECTED', detail
        except OSError as exc:
            detail = f'{type(exc).__name__}: {exc}'
            self._log('connect_error', error=detail)
            return 'UNREACHABLE', detail
        self.client.loop_start()
        wait_until(lambda: self.connack is not None or self.closed, timeout)
        if self.connack == 0 and not self.closed:
            return 'ACCEPTED', 'CONNACK 0'
        if self.connack:
            return 'REJECTED', f'CONNACK {self.connack}'
        if self.closed:
            return 'REJECTED', (self.errors[-1] if self.errors else f"closed: {self.closed[0]['reason']}")
        return 'NO_RESPONSE', 'no CONNACK within timeout'

    def closed_by_peer(self):
        return [c for c in self.closed if not c['cleanup']]

    def alive(self):
        return self.client.is_connected() and not self.closed_by_peer()

    def publish(self, topic, payload, timeout=6):
        info = self.client.publish(topic, payload, qos=1, retain=False)
        wait_until(lambda: info.mid in self.acks or bool(self.closed), timeout)
        return self.acks.get(info.mid)

    def subscribe(self, topic_filter, timeout=6):
        _, mid = self.client.subscribe(topic_filter, qos=1)
        wait_until(lambda: mid in self.subacks or bool(self.closed), timeout)
        return self.subacks.get(mid)

    def received(self, payload, seconds):
        wait_until(lambda: payload in self.messages, seconds)
        return self.messages.count(payload)

    def abort(self):
        """Link loss: close TCP without MQTT DISCONNECT; the broker keeps the session."""
        self.cleanup = True
        sock = self.client.socket()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        wait_until(lambda: self.client.socket() is None, 3)
        self.client.loop_stop()

    def close(self):
        self.cleanup = True
        try:
            if self.client.is_connected():
                self.client.disconnect()
        finally:
            self.client.loop_stop()


def granted(codes):
    return codes is not None and all(code < 128 for code in codes)


def denied(codes):
    return codes is not None and all(code >= 128 for code in codes)


# --------------------------------------------------------------------------- harness

class Harness:
    def __init__(self, cfg, fleet, broker, target, run_dir, gateway_a):
        self.cfg, self.fleet, self.broker, self.target, self.run_dir = cfg, fleet, broker, target, run_dir
        self.run_id = run_dir.name
        self.rec = Recorder()
        self.observe_s = target.get('observe_s', 3.0)
        self.session_expiry = target.get('session_expiry_s', 300)
        self.gw = _pick_gateways(fleet, gateway_a)
        self.ingest, self.command = cfg['services']['ingest'], cfg['services']['command']
        self.d2c_all = f"{cfg['topics']['base']}/+/gateways/+/d2c/#"
        self.clients = []

    def files(self, identity):
        return identity_files(self.broker.certs, identity)

    def negative(self, name):
        folder = self.broker.certs / 'negative' / name
        files = folder / 'client.crt', folder / 'client.key'
        if not all(f.exists() for f in files):
            raise Inconclusive(f'{folder} missing: run make negative-certs')
        return files

    def client(self, label, client_id, files):
        probe = ProbeClient(self, label, client_id, files)
        self.clients.append(probe)
        return probe

    def connect(self, label, identity, client_id=None, **kwargs):
        """Open a connection that must succeed; otherwise the case is inconclusive."""
        probe = self.client(label, client_id or identity, self.files(identity))
        outcome, detail = probe.open(**kwargs)
        if outcome != 'ACCEPTED':
            raise Inconclusive(f'{label}: authorized connection failed ({detail})')
        return probe

    def id(self, key):
        return self.gw[key]['gateway_id']

    def base(self, key, plant_of=None):
        return gateway_base(self.cfg, self.gw[plant_of or key]['plant_id'], self.id(key))

    def topic(self, key, direction, case_id, plant_of=None):
        return f'{self.base(key, plant_of)}/{direction}/simulation/{self.run_id}/{case_id}'

    def payload(self, case_id):
        return f'ENTC63|{case_id}|'.encode() + os.urandom(24).hex().encode()

    def purge_session(self, identity):
        """Remove a persistent session left by a case (Clean Start, expiry 0)."""
        probe = self.client(f'purge:{identity}', identity, self.files(identity))
        if probe.open(clean_start=True, session_expiry=0)[0] == 'ACCEPTED':
            probe.close()

    def close_all(self):
        for probe in self.clients:
            try:
                probe.close()
            except Exception:  # cleanup must not hide the case result
                pass
        self.clients = []


def _pick_gateways(fleet, gateway_a):
    """A: target of the negative certificates. B, C: two gateways of one other plant."""
    by_id = {g['gateway_id']: g for g in fleet['gateways']}
    if gateway_a not in by_id:
        raise SystemExit(f'{gateway_a} is not in the fleet')
    a = by_id[gateway_a]
    for plant in fleet['plants']:
        if plant['plant_id'] != a['plant_id'] and len(plant['gateways']) >= 2:
            b, c = plant['gateways'][:2]
            return {'A': a, 'B': by_id[b], 'C': by_id[c]}
    raise SystemExit('fleet needs a second plant with at least two gateways (cross-gateway tests)')


def _verdict_reject(outcome):
    return {'REJECTED': 'PASS', 'ACCEPTED': 'FAIL'}.get(outcome, 'INCONCLUSIVE')


def _probe_publish(h, case_id, actor, topic, witness=None, client_id=None, files=None):
    """`actor` publishes an opaque payload; `witness` (identity, filter) or 'self' watches delivery."""
    payload = h.payload(case_id)
    watcher = None
    if witness and witness != 'self':
        watcher = h.connect(f'{case_id}:witness', witness[0])
        if not granted(watcher.subscribe(witness[1])):
            raise Inconclusive('witness could not subscribe')
    probe = h.client(case_id, client_id or actor, files or h.files(actor))
    outcome, detail = probe.open()
    if outcome in ('UNREACHABLE', 'NO_RESPONSE'):
        raise Inconclusive(f'{case_id}: {outcome} ({detail})')
    if outcome != 'ACCEPTED':
        return {'connect': f'{outcome} ({detail})', 'puback': None, 'delivered': 0, 'closed': True}
    if witness == 'self':
        watcher = probe
        if not granted(probe.subscribe(witness_filter_for_self(topic))):
            raise Inconclusive('actor could not subscribe to watch its own publish')
    code = probe.publish(topic, payload)
    delivered = watcher.received(payload, h.observe_s) if watcher else None
    closed = bool(probe.closed_by_peer())
    probe.close()
    return {'connect': 'ACCEPTED', 'puback': code, 'delivered': delivered, 'closed': closed}


def witness_filter_for_self(topic):
    return topic.rsplit('/', 3)[0] + '/#'


def _publish_denied(obs):
    seen = 'no authorized reader' if obs['delivered'] is None else obs['delivered']
    text = f"PUBACK {obs['puback']}; delivered {seen}" + ('; disconnected' if obs['closed'] else '')
    if obs['delivered']:
        return 'FAIL', text
    if (obs['puback'] is not None and obs['puback'] >= 128) or obs['closed']:
        return 'PASS', text
    if obs['puback'] in ACCEPTED_CODES:
        # Accepted without delivery: only PARTIAL if a witness could have seen it.
        return ('PARTIAL' if obs['delivered'] == 0 else 'FAIL'), text + ' (accepted, not signalled as denied)'
    return 'INCONCLUSIVE', text


def _probe_subscribe(h, case_id, actor, topic_filter, triggers):
    """`actor` subscribes; each trigger (publisher identity or 'self', topic) publishes an
    opaque payload into the filter. Returns SUBACK codes and how many payloads arrived."""
    probe = h.connect(case_id, actor)
    codes = probe.subscribe(topic_filter)
    if probe.closed_by_peer():  # some brokers disconnect on a denied SUBSCRIBE
        return {'suback': codes, 'triggers': 0, 'delivered': 0, 'closed': True}
    payloads = []
    for publisher, topic in triggers:
        payload = h.payload(case_id)
        sender = probe if publisher == 'self' else h.connect(f'{case_id}:trigger-{publisher}', publisher)
        code = sender.publish(topic, payload)
        if code not in ACCEPTED_CODES:
            raise Inconclusive(f'authorized trigger publish by {publisher} not accepted (PUBACK {code})')
        payloads.append(payload)
    wait_until(lambda: all(p in probe.messages for p in payloads), h.observe_s)
    delivered = sum(p in probe.messages for p in payloads)
    return {'suback': codes, 'triggers': len(payloads), 'delivered': delivered,
            'closed': bool(probe.closed_by_peer())}


def _subscribe_denied(obs):
    text = (f"SUBACK {obs['suback']}; delivered {obs['delivered']}/{obs['triggers']}"
            + ('; disconnected' if obs['closed'] else ''))
    if obs['delivered']:
        return 'FAIL', text
    if denied(obs['suback']) or obs['closed']:
        return 'PASS', text
    if granted(obs['suback']):
        return 'PARTIAL', text + ' (nothing delivered, but subscription not signalled as denied)'
    return 'INCONCLUSIVE', text


# --------------------------------------------------------------------------- cases: mTLS

@case('MTLS-01', 'R01', 'Each simulated gateway connects with its own certificate (Client ID = CN)', 'ACCEPT')
def mtls_valid(h):
    notes, fingerprints = [], set()
    for key in 'ABC':
        gid = h.id(key)
        crt, _ = h.files(gid)
        fingerprints.add(hashlib.sha256(crt.read_bytes()).hexdigest())
        probe = h.client(f'MTLS-01:{gid}', gid, h.files(gid))
        outcome, detail = probe.open()
        if outcome in ('UNREACHABLE', 'NO_RESPONSE'):
            raise Inconclusive(f'broker not reachable: {detail}')
        notes.append(f'{gid}: {outcome}')
        probe.close()
    ok = all(n.endswith('ACCEPTED') for n in notes) and len(fingerprints) == 3
    return ('PASS' if ok else 'FAIL'), '; '.join(notes) + f'; distinct certificates: {len(fingerprints)}/3'


def _reject_case(files_fn):
    def run(h):
        probe = h.client(run.case_id, h.id('A'), files_fn(h))
        outcome, detail = probe.open()
        return _verdict_reject(outcome), f'{outcome} ({detail})'
    return run


for _id, _req, _title, _files, _mandatory in [
    ('MTLS-02', 'R02', 'No client certificate', lambda h: None, True),
    ('MTLS-03', 'R03', 'Certificate from a rogue CA with the identical CA name, CN = real Gateway ID',
     lambda h: h.negative('untrusted-ca'), True),
    ('MTLS-04', 'R03', 'Self-signed certificate, CN = real Gateway ID', lambda h: h.negative('self-signed'), True),
    ('MTLS-05', 'R04', 'Expired certificate (lab CA)', lambda h: h.negative('expired'), True),
    ('MTLS-06', 'R04', 'Certificate before notBefore (lab CA)', lambda h: h.negative('not-yet-valid'), True),
    ('MTLS-07', 'R04', 'Certificate without clientAuth EKU (profile OPEN, ENTC-31)',
     lambda h: h.negative('wrong-eku'), False),
    ('MTLS-08', 'R04', 'Revoked certificate (CRL; revocation strategy OPEN, ENTC-58/31)',
     lambda h: h.negative('revoked'), False),
]:
    _fn = _reject_case(_files)
    _fn.case_id = _id
    case(_id, _req, _title, 'REJECT', _mandatory)(_fn)


# --------------------------------------------------------------------------- cases: identity

@case('ID-01', 'R06', 'Certificate of gateway A with Client ID of gateway B', 'REJECT')
def id_mismatch(h):
    legit = h.connect('ID-01:legit', h.id('B'))
    probe = h.client('ID-01', h.id('B'), h.files(h.id('A')))
    outcome, detail = probe.open()
    text = f'{outcome} ({detail})'
    if outcome == 'ACCEPTED':
        time.sleep(1)
        text += f"; legitimate session of {h.id('B')} " + ('kept' if legit.alive() else 'DISPLACED')
    return _verdict_reject(outcome), text


@case('ID-02', 'R05', 'With A\'s certificate but B\'s Client ID, B\'s namespace stays closed', 'DENY')
def id_binding(h):
    obs = _probe_publish(h, 'ID-02', h.id('A'), h.topic('B', 'd2c', 'ID-02'), witness=(h.ingest, h.d2c_all),
                         client_id=h.id('B'), files=h.files(h.id('A')))
    if obs['connect'] != 'ACCEPTED':
        return 'PASS', f"connection rejected ({obs['connect']}): identity bound at CONNECT"
    verdict, text = _publish_denied(obs)
    return verdict, 'connection accepted; publish to B d2c: ' + text


@case('DUP-01', 'R11', 'Second connection with the Client ID of an active gateway', 'REJECT_NEW_KEEP_EXISTING')
def duplicate_client_id(h):
    first = h.connect('DUP-01:existing', h.id('A'))
    second = h.client('DUP-01:new', h.id('A'), h.files(h.id('A')))
    outcome, detail = second.open()
    time.sleep(1)
    existing_ok = first.alive() and first.publish(h.topic('A', 'd2c', 'DUP-01'), h.payload('DUP-01')) in ACCEPTED_CODES
    peer = first.closed_by_peer()
    existing = 'still connected and publishing' if existing_ok else (
        f"closed by {'server DISCONNECT' if peer and peer[0]['server_packet'] else 'transport'}"
        f" (reason {peer[0]['code']} {peer[0]['reason']})" if peer else 'not usable')
    verdict = 'PASS' if outcome == 'REJECTED' and existing_ok else 'FAIL'
    return verdict, f'new: {outcome} ({detail}); existing: {existing}'


# --------------------------------------------------------------------------- cases: ACL publish

@case('ACL-01', 'R08', 'Gateway A publishes to its own d2c namespace (positive control)', 'ALLOW')
def acl_own_d2c(h):
    obs = _probe_publish(h, 'ACL-01', h.id('A'), h.topic('A', 'd2c', 'ACL-01'), witness=(h.ingest, h.d2c_all))
    ok = obs['puback'] in ACCEPTED_CODES and obs['delivered']
    return ('PASS' if ok else 'FAIL'), f"PUBACK {obs['puback']}; delivered {obs['delivered']}"


def _deny_publish_case(case_id, actor_key, topic_fn, witness_fn):
    def run(h):
        return _publish_denied(_probe_publish(h, case_id, h.id(actor_key), topic_fn(h), witness=witness_fn(h)))
    return run


for _id, _req, _title, _actor, _topic, _witness in [
    ('ACL-02', 'R10', 'A publishes into B\'s d2c namespace (other plant)', 'A',
     lambda h: h.topic('B', 'd2c', 'ACL-02'), lambda h: (h.ingest, h.d2c_all)),
    ('ACL-03', 'R10', 'C publishes into B\'s d2c namespace (same plant, other gateway)', 'C',
     lambda h: h.topic('B', 'd2c', 'ACL-03'), lambda h: (h.ingest, h.d2c_all)),
    ('ACL-04', 'R10', 'A publishes under its own Gateway ID but in B\'s plant (plant spoofing)', 'A',
     lambda h: h.topic('A', 'd2c', 'ACL-04', plant_of='B'), lambda h: (h.ingest, h.d2c_all)),
    ('ACL-05', 'R08', 'A publishes into its own c2d namespace (wrong direction)', 'A',
     lambda h: h.topic('A', 'c2d', 'ACL-05'), lambda h: 'self'),
    ('ACL-06', 'R07', 'A publishes outside every granted namespace', 'A',
     lambda h: f"{h.cfg['topics']['base']}/unassigned/{h.run_id}/ACL-06", lambda h: None),
]:
    case(_id, _req, _title, 'DENY')(_deny_publish_case(_id, _actor, _topic, _witness))


# --------------------------------------------------------------------------- cases: ACL subscribe

@case('ACL-07', 'R09', 'Gateway A subscribes to its own c2d namespace (positive control)', 'ALLOW')
def acl_own_c2d(h):
    obs = _probe_subscribe(h, 'ACL-07', h.id('A'), f"{h.base('A')}/c2d/#",
                           [(h.command, h.topic('A', 'c2d', 'ACL-07'))])
    ok = granted(obs['suback']) and obs['delivered'] == obs['triggers']
    return ('PASS' if ok else 'FAIL'), f"SUBACK {obs['suback']}; delivered {obs['delivered']}/{obs['triggers']}"


def _deny_subscribe_case(case_id, actor_key, filter_fn, triggers_fn):
    def run(h):
        return _subscribe_denied(_probe_subscribe(h, case_id, h.id(actor_key), filter_fn(h), triggers_fn(h)))
    return run


for _id, _req, _title, _actor, _filter, _triggers in [
    ('ACL-08', 'R10', 'A subscribes to B\'s c2d namespace (other plant)', 'A',
     lambda h: f"{h.base('B')}/c2d/#", lambda h: [(h.command, h.topic('B', 'c2d', 'ACL-08'))]),
    ('ACL-09', 'R10', 'C subscribes to B\'s c2d namespace (same plant, other gateway)', 'C',
     lambda h: f"{h.base('B')}/c2d/#", lambda h: [(h.command, h.topic('B', 'c2d', 'ACL-09'))]),
    ('ACL-10', 'R09', 'A subscribes to its own d2c namespace (wrong direction)', 'A',
     lambda h: f"{h.base('A')}/d2c/#", lambda h: [('self', h.topic('A', 'd2c', 'ACL-10'))]),
    ('ACL-11', 'R10', 'A subscribes to B\'s d2c telemetry (other plant)', 'A',
     lambda h: f"{h.base('B')}/d2c/#", lambda h: [(h.id('B'), h.topic('B', 'd2c', 'ACL-11'))]),
    ('ACL-12', 'R10', 'A subscribes to the whole tree with a wildcard', 'A',
     lambda h: f"{h.cfg['topics']['base']}/#",
     lambda h: [(h.id('B'), h.topic('B', 'd2c', 'ACL-12')), (h.command, h.topic('C', 'c2d', 'ACL-12'))]),
]:
    case(_id, _req, _title, 'DENY')(_deny_subscribe_case(_id, _actor, _filter, _triggers))


@case('ACL-13', 'R07', 'Valid certificate, Gateway ID unknown to the fleet: publish and subscribe', 'DENY')
def acl_unknown_gateway(h):
    files = h.negative('unknown-gateway')
    base = gateway_base(h.cfg, h.gw['A']['plant_id'], UNKNOWN_GATEWAY)
    pub = _probe_publish(h, 'ACL-13', UNKNOWN_GATEWAY, f'{base}/d2c/simulation/{h.run_id}/ACL-13',
                         witness=(h.ingest, h.d2c_all), files=files)
    if pub['connect'] != 'ACCEPTED':
        return 'PASS', f"connection rejected ({pub['connect']})"
    pub_verdict, pub_text = _publish_denied(pub)
    probe = h.client('ACL-13:subscribe', UNKNOWN_GATEWAY, files)
    if probe.open()[0] != 'ACCEPTED':
        raise Inconclusive('unknown gateway accepted for publish but not for subscribe')
    codes = probe.subscribe(f'{base}/c2d/#')
    payload = h.payload('ACL-13')
    trigger = h.connect('ACL-13:trigger', h.command).publish(f'{base}/c2d/simulation/{h.run_id}/ACL-13', payload)
    if trigger not in ACCEPTED_CODES:
        raise Inconclusive(f'authorized trigger publish not accepted (PUBACK {trigger})')
    sub_verdict, sub_text = _subscribe_denied({'suback': codes, 'triggers': 1, 'closed': bool(probe.closed_by_peer()),
                                               'delivered': min(probe.received(payload, h.observe_s), 1)})
    order = ['FAIL', 'INCONCLUSIVE', 'PARTIAL', 'PASS']
    verdict = min(pub_verdict, sub_verdict, key=order.index)
    return verdict, f'publish: {pub_text}; subscribe: {sub_text}'


# --------------------------------------------------------------------------- cases: QoS / session

@case('QOS-01', 'R12', 'QoS 1 publish is acknowledged and delivered with QoS 1', 'PUBACK_AND_DELIVERY')
def qos_ack(h):
    witness = h.connect('QOS-01:witness', h.ingest)
    if not granted(witness.subscribe(h.d2c_all)):
        raise Inconclusive('witness could not subscribe')
    payload = h.payload('QOS-01')
    code = h.connect('QOS-01', h.id('A')).publish(h.topic('A', 'd2c', 'QOS-01'), payload)
    copies = witness.received(payload, h.observe_s)
    qos = [e.get('qos') for e in h.rec.events if e['actor'] == 'QOS-01:witness' and e['event'] == 'message_received']
    ok = code in ACCEPTED_CODES and copies >= 1 and qos and qos[-1] == 1
    return ('PASS' if ok else 'FAIL'), f'PUBACK {code}; delivered {copies}x with QoS {qos[-1] if qos else None}'


@case('QOS-02', 'R12', 'Unacknowledged QoS 1 publish at link loss is redelivered after reconnect',
      'AT_LEAST_ONCE')
def qos_redelivery(h):
    witness = h.connect('QOS-02:witness', h.ingest)
    if not granted(witness.subscribe(h.d2c_all)):
        raise Inconclusive('witness could not subscribe')
    gid, state = h.id('A'), {}
    client = new_client(gid, h.broker, *h.files(gid))
    client.on_connect = lambda c, u, f, r, p: state.update(connack=r.value, session_present=bool(f.session_present))
    client.on_publish = lambda c, u, mid, r, p: state.update(puback=r.value)

    def connect(clean_start):
        state.pop('connack', None)
        client.connect(h.broker.host, h.broker.port, keepalive=30, clean_start=clean_start,
                       properties=connect_properties(h.session_expiry))
        deadline = time.monotonic() + 6
        while 'connack' not in state and client.socket() is not None and time.monotonic() < deadline:
            client.loop(0.05)
        return state.get('connack') == 0

    try:
        if not connect(clean_start=True):
            raise Inconclusive('gateway A could not connect')
        payload = h.payload('QOS-02')
        # Manual network loop: publish() writes immediately, the PUBACK is never read
        # because the link is cut right away. paho keeps the message in flight.
        client.publish(h.topic('A', 'd2c', 'QOS-02'), payload, qos=1)
        client.socket().shutdown(socket.SHUT_RDWR)
        deadline = time.monotonic() + 3
        while client.socket() is not None and time.monotonic() < deadline:
            client.loop(0.05)
        h.rec('QOS-02', 'link_cut', puback_before_cut=state.get('puback'))
        time.sleep(0.3)
        if not connect(clean_start=False):
            raise Inconclusive('reconnect failed')
        deadline = time.monotonic() + 6
        while 'puback' not in state and time.monotonic() < deadline:
            client.loop(0.05)
        client.disconnect()
    finally:
        client.loop_stop()
    copies = witness.received(payload, h.observe_s)
    ok = state.get('session_present') and state.get('puback') in ACCEPTED_CODES and copies >= 1
    h.purge_session(gid)
    return ('PASS' if ok else 'FAIL'), (f"session_present {state.get('session_present')}; PUBACK after reconnect "
                                        f"{state.get('puback')}; delivered {copies}x (duplicates are allowed)")


@case('SES-01', 'R13', 'Command sent while the gateway is offline arrives after reconnect with Clean Start = false',
      'SESSION_RESUMED')
def session_resume(h):
    gid, c2d = h.id('A'), f"{h.base('A')}/c2d/#"
    first = h.connect('SES-01:first', gid, clean_start=True, session_expiry=h.session_expiry)
    if not granted(first.subscribe(c2d)):
        raise Inconclusive('subscription to own c2d failed')
    first.abort()
    time.sleep(0.5)
    payload = h.payload('SES-01')
    code = h.connect('SES-01:command', h.command).publish(h.topic('A', 'c2d', 'SES-01'), payload)
    if code not in ACCEPTED_CODES:
        raise Inconclusive(f'command not accepted (PUBACK {code})')
    resumed = h.connect('SES-01:resume', gid, clean_start=False, session_expiry=h.session_expiry)
    copies = resumed.received(payload, h.observe_s)
    ok = resumed.session_present and copies >= 1
    resumed.close()
    h.purge_session(gid)
    return ('PASS' if ok else 'FAIL'), (f'command PUBACK {code}; reconnect session_present {resumed.session_present};'
                                        f' queued command delivered {copies}x')


@case('SES-02', 'R13', 'Clean Start = true discards the session and its queued messages', 'SESSION_DISCARDED',
      mandatory=False)
def session_discard(h):
    gid, c2d = h.id('A'), f"{h.base('A')}/c2d/#"
    first = h.connect('SES-02:first', gid, clean_start=True, session_expiry=h.session_expiry)
    if not granted(first.subscribe(c2d)):
        raise Inconclusive('subscription to own c2d failed')
    first.abort()
    time.sleep(0.5)
    payload = h.payload('SES-02')
    h.connect('SES-02:command', h.command).publish(h.topic('A', 'c2d', 'SES-02'), payload)
    fresh = h.connect('SES-02:fresh', gid, clean_start=True, session_expiry=0)
    copies = fresh.received(payload, 1.0)
    ok = not fresh.session_present and copies == 0
    return ('PASS' if ok else 'FAIL'), f'session_present {fresh.session_present}; stale command delivered {copies}x'


@case('REC-01', 'R14', 'Simultaneous link loss of many gateways, reconnect with jittered exponential backoff',
      'ALL_RESUMED_SPREAD')
def reconnect_spread(h):
    count = min(h.target.get('reconnect_gateways', 10), len(h.fleet['gateways']))
    window = h.target.get('reconnect_window_s', 5.0)
    gateways = [g['gateway_id'] for g in h.fleet['gateways'][:count]]
    for gid in gateways:
        probe = h.connect(f'REC-01:{gid}', gid, clean_start=True, session_expiry=h.session_expiry)
        if not granted(probe.subscribe(f"{gateway_base(h.cfg, _plant(h, gid), gid)}/c2d/#")):
            raise Inconclusive(f'{gid}: subscription failed')
    for probe in list(h.clients):
        probe.abort()
    # Stratified full jitter with a fixed seed: every gateway picks a random instant in its
    # own slot of the window, so attempts are spread and the schedule is identical per run.
    rng = random.Random(f"{h.cfg['seed']}:reconnect")
    slot = window / count
    schedule = [((i + rng.random()) * slot, gid) for i, gid in enumerate(rng.sample(gateways, count))]
    start, attempts, resumed = time.monotonic(), [], {}
    for delay, gid in schedule:
        time.sleep(max(start + delay - time.monotonic(), 0))
        backoff = 0.5
        for attempt in range(5):
            attempts.append(time.monotonic() - start)
            probe = h.client(f'REC-01:{gid}:attempt{attempt + 1}', gid, h.files(gid))
            if probe.open(clean_start=False, session_expiry=h.session_expiry)[0] == 'ACCEPTED':
                resumed[gid] = probe.session_present
                break
            time.sleep(backoff * rng.uniform(0.5, 1.0))
            backoff = min(backoff * 2, 8.0)
    peak = max(sum(1 for a in attempts if s <= a < s + 1) for s in attempts)
    span = attempts[-1] - attempts[0]
    h.close_all()
    for gid in gateways:
        h.purge_session(gid)
    ok = len(resumed) == count and all(resumed.values()) and span >= 0.5 * window
    return ('PASS' if ok else 'FAIL'), (f'{count} gateways dropped at once; {len(attempts)} reconnect attempts over '
                                        f'{span:.1f} s (peak {peak}/s, window {window} s); '
                                        f'session resumed {sum(resumed.values())}/{count}')


def _plant(h, gid):
    return next(g['plant_id'] for g in h.fleet['gateways'] if g['gateway_id'] == gid)


# --------------------------------------------------------------------------- phases

def run_cases(cfg, fleet, broker, target, run_dir, gateway_a='gw-sim-000001', only=None):
    h = Harness(cfg, fleet, broker, target, run_dir, gateway_a)
    started = time.time()
    results = []
    for c in CASES:
        if only and c.id != 'MTLS-01' and not any(c.id.startswith(prefix) for prefix in only):
            continue
        h.rec(c.id, 'case_start', expected=c.expected)
        try:
            verdict, observed = c.fn(h)
        except Inconclusive as exc:
            verdict, observed = 'INCONCLUSIVE', str(exc)
        except Exception as exc:  # recorded as evidence; never a PASS
            verdict, observed = 'INCONCLUSIVE', f'harness error: {type(exc).__name__}: {exc}'
        finally:
            h.close_all()
        h.rec(c.id, 'case_result', verdict=verdict, observed=observed)
        results.append({'id': c.id, 'requirement': c.requirement, 'title': c.title, 'expected': c.expected,
                        'mandatory': c.mandatory, 'verdict': verdict, 'observed': observed})
        print(f'  {c.id:8} {verdict:12} {observed[:110]}', flush=True)
        time.sleep(0.2)
    control = next((r for r in results if r['id'] == 'MTLS-01'), None)
    if control is None or control['verdict'] != 'PASS':
        # Without a working positive control no rejection or denial is evidence.
        for r in results:
            if r['id'] != 'MTLS-01' and r['verdict'] == 'PASS':
                r['verdict'] = 'INCONCLUSIVE'
                r['observed'] += ' [positive control MTLS-01 did not pass]'
    run = {'run_id': run_dir.name, 'target': target.get('name'), 'broker': f'{broker.host}:{broker.port}',
           'gateways': {k: v['gateway_id'] for k, v in h.gw.items()}, 'observe_s': h.observe_s,
           'started_epoch': int(started), 'finished_epoch': int(time.time()) + 1, 'only': only,
           'results': results}
    write_json(run_dir / 'results.json', run)
    write_jsonl(run_dir / 'events.jsonl', h.rec.events)
    return run


SECRET = re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:password|passwd)\s*[=:]\s*\S+')
LOG_CASES = [
    ('LOG-01', 'Accepted connections are logged with client and certificate identity', 'connect_accepted'),
    ('LOG-02', 'Authentication / TLS failures are logged', 'auth_failure'),
    ('LOG-03', 'ACL denials are logged', 'acl_denied'),
    ('LOG-04', 'Disconnects are logged', 'disconnect'),
]


def log_cases(target, run, broker_log, run_dir):
    patterns = target.get('log', {})
    results = []
    lines = []
    if broker_log and Path(broker_log).is_file():
        stamp = re.compile(patterns.get('timestamp', r'(\d{10})'))
        for line in Path(broker_log).read_text(errors='replace').splitlines():
            m = stamp.search(line)
            if m and run['started_epoch'] - 5 <= int(m.group(1)) <= run['finished_epoch'] + 30:
                lines.append(line)
    for case_id, title, key in LOG_CASES:
        result = {'id': case_id, 'requirement': 'R15', 'title': title, 'expected': 'LOGGED', 'mandatory': True}
        if not lines or key not in patterns:
            result.update(verdict='INCONCLUSIVE', observed='no broker log for the run window'
                          if not lines else f'no log pattern "{key}" in target profile')
        else:
            hits = [line for line in lines if re.search(patterns[key], line)]
            result.update(verdict='PASS' if hits else 'FAIL',
                          observed=f'{len(hits)} matching lines' + (f'; e.g. "{hits[0].strip()[:140]}"' if hits else ''))
        results.append(result)
    scanned, found = 0, []
    for path in [Path(broker_log)] if broker_log and Path(broker_log).is_file() else []:
        scanned += 1
        found += [str(path)] if SECRET.search(path.read_bytes()) else []
    for path in run_dir.rglob('*'):
        if path.is_file() and path != (Path(broker_log) if broker_log else None):
            scanned += 1
            found += [str(path)] if SECRET.search(path.read_bytes()) else []
    results.append({'id': 'LOG-05', 'requirement': 'R15', 'expected': 'NO_SECRETS', 'mandatory': True,
                    'title': 'No private keys or credentials in the broker log or the evidence',
                    'verdict': 'FAIL' if found else ('PASS' if lines else 'INCONCLUSIVE'),
                    'observed': f'{scanned} files scanned; secrets found in: {found}' if found else
                                f'{scanned} files scanned, no private key or credential pattern'
                                + ('' if lines else '; broker log missing')})
    return results


def report(target, run_dir, broker_log=None, label=None):
    run = json.loads((run_dir / 'results.json').read_text())
    results = run['results'] + log_cases(target, run, broker_log, run_dir)
    for r in results:
        if r['verdict'] in ('FAIL', 'PARTIAL'):
            key = r['id'] if r['id'] in FINDINGS else 'SUBSCRIBE' if 'SUBACK' in r['observed'] else None
            if key:
                r['finding'] = FINDINGS[key]
    mandatory = [r for r in results if r['mandatory']]
    missing = [c.id for c in CASES if c.mandatory and c.id not in {r['id'] for r in results}]
    # A filtered or aborted run never counts as acceptance.
    accepted = not missing and all(r['verdict'] == 'PASS' for r in mandatory)
    requirements = []
    for req_id, text in REQUIREMENTS:
        cases = [r for r in results if r['requirement'] == req_id and r['mandatory']]
        verdicts = {r['verdict'] for r in cases}
        verdict = next((v for v in ('FAIL', 'INCONCLUSIVE', 'PARTIAL') if v in verdicts), 'PASS' if cases else 'N/A')
        advisory = [f"{r['id']} {r['verdict']}" for r in results
                    if r['requirement'] == req_id and not r['mandatory']]
        requirements.append({'id': req_id, 'requirement': text, 'verdict': verdict, 'advisory': advisory,
                             'cases': [r['id'] for r in results if r['requirement'] == req_id]})
    counts = {v: sum(r['verdict'] == v for r in mandatory) for v in VERDICTS}
    summary = {'run_id': run['run_id'], 'target': run['target'], 'broker_label': label or run['target'],
               'broker': run['broker'], 'gateways': run['gateways'],
               'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               'accepted': accepted, 'exit': 0 if accepted else 1, 'mandatory_counts': counts,
               'mandatory_not_run': missing,
               'requirements': requirements, 'results': results}
    write_json(run_dir / 'report.json', summary)
    (run_dir / 'report.md').write_text(_markdown(summary))
    return summary


def _markdown(s):
    esc = lambda text: str(text).replace('|', '\\|')
    lines = [f"# ENTC-63 acceptance — {s['broker_label']}", '',
             f"Run `{s['run_id']}` against `{s['broker']}` ({s['generated_utc']}). Gateways: "
             + ', '.join(f'{k} = `{v}`' for k, v in s['gateways'].items()) + '.', '',
             f"**Result: {'ACCEPTED' if s['accepted'] else 'NOT ACCEPTED'}** — mandatory cases: "
             + ', '.join(f'{n} {v}' for v, n in s['mandatory_counts'].items()) + '.'
             + (f" Not run: {', '.join(s['mandatory_not_run'])} (incomplete run, never accepted)."
                if s['mandatory_not_run'] else ''), '',
             '## Requirements', '', '| ID | Requirement | Result | Cases | Advisory |', '|---|---|---|---|---|']
    lines += [f"| {r['id']} | {esc(r['requirement'])} | **{r['verdict']}** | {', '.join(r['cases'])} | "
              f"{', '.join(r['advisory'])} |" for r in s['requirements']]
    findings = {}
    for r in s['results']:
        if 'finding' in r:
            findings.setdefault(r['finding'], []).append(f"{r['id']} {r['verdict']}")
    if findings:
        lines += ['', '## Broker limitations found', '']
        lines += [f"- **{', '.join(ids)}**: {text}" for text, ids in findings.items()]
    lines += ['', '## Cases', '', '| Case | Req. | Test | Expected | Observed | Result |', '|---|---|---|---|---|---|']
    for r in s['results']:
        flag = '' if r['mandatory'] else ' (advisory)'
        lines.append(f"| {r['id']} | {r['requirement']} | {esc(r['title'])}{flag} | {r['expected']} | "
                     f"{esc(r['observed'])} | **{r['verdict']}** |")
    lines += ['', 'PASS = required behaviour observed. FAIL = contrary behaviour observed. PARTIAL = access blocked '
              'in effect but not signalled as required. INCONCLUSIVE = no evidence (setup, timeout, missing log). '
              'Advisory cases do not affect the result. Transport-level evidence only (PUBACK != application ACK).']
    return '\n'.join(lines) + '\n'


def load_target(path):
    return tomllib.loads(Path(path).read_text())
