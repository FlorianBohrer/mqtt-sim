#!/usr/bin/env sh
# Spielt die aus der Flotte generierten ACL-Regeln ueber die Bevywise-REST-API ein.
#   BEVYWISE_API_URL   z. B. https://broker.example.com:8080   (Pflicht)
#   BEVYWISE_API_AUTH  kompletter Auth-Header, z. B. "Authorization: Bearer <token>"
#                      (Auth-Verfahren der API laut Bevywise-Doku pruefen)
#   DRY_RUN=1          nur anzeigen, nichts senden
# Endpoint und Felder (clientid, publish_access/_topics, subscribe_access/_topics) laut
# Bevywise-Doku; HTTP-Methode (POST) und Listenformat der Topics sind zu bestaetigen.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
REQ="$ROOT/brokers/bevywise/generated/acl-requests.json"
[ -f "$REQ" ] || { echo "Missing $REQ: run 'make bevywise-config' first." >&2; exit 1; }
[ -n "${BEVYWISE_API_URL:-}" ] || [ "${DRY_RUN:-0}" = 1 ] || { echo 'Set BEVYWISE_API_URL (or DRY_RUN=1).' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'python3 required' >&2; exit 1; }
python3 - "$REQ" <<'PY' | while IFS= read -r BODY; do
import json, sys
for item in json.load(open(sys.argv[1])):
    print(json.dumps(item, separators=(',', ':')))
PY
  if [ "${DRY_RUN:-0}" = 1 ]; then
    printf 'POST /crystalmq/api/v1/acl %s\n' "$BODY"
  else
    curl -fsS -X POST "$BEVYWISE_API_URL/crystalmq/api/v1/acl" \
      -H 'Content-Type: application/json' ${BEVYWISE_API_AUTH:+-H "$BEVYWISE_API_AUTH"} \
      -d "$BODY" >/dev/null && printf 'OK   %s\n' "$(printf '%s' "$BODY" | cut -c1-60)"
  fi
done
