#!/usr/bin/env sh
# Synthetische Flotte erzeugen (sim/config.toml):
#   synthetic/fleet.json, synthetic/dataset/*, mosquitto/config/acl (generiert)
# und fuer jedes Gateway / jede Service-Identitaet ein Zertifikat nach dem
# Prototyp-Ablauf aus 02_create_gateway.sh (P-256, CSR, Signatur durch die Lab-CA).
# Voraussetzung: make init. Vorhandene Zertifikate bleiben unveraendert.
# Laeuft der Compose-Broker, wird die neue ACL per SIGHUP geladen.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/sim_common.sh"

[ -r certs/ca/ca.key ] && [ -r certs/ca/ca.crt ] || die 'Lab CA missing. Run make init first.'
[ ! -e mosquitto/config/.replacement-test-lock ] || die 'Test 09/10 ACL lock present; recover it first.'

printf '[1/3] Generate fleet, dataset and ACL\n'
run_sim generate

printf '\n[2/3] Certificates for fleet identities\n'
CREATED=0
create_missing() {
  GROUP=$1
  while IFS= read -r ID; do
    [ -n "$ID" ] || continue
    # Keep valid certificates; re-issue those from an earlier CA (e.g. after make init).
    if [ -f "certs/$GROUP/$ID/gateway.crt" ] &&
       openssl verify -CAfile certs/ca/ca.crt "certs/$GROUP/$ID/gateway.crt" >/dev/null 2>&1; then
      continue
    fi
    rm -rf "certs/$GROUP/$ID"
    OUT=$(./scripts/02_create_gateway.sh "$ID" "$GROUP" 2>&1) ||
      { printf '%s\n' "$OUT" >&2; die "certificate creation failed for $ID"; }
    CREATED=$((CREATED + 1))
  done
}
create_missing gateways < synthetic/gateways.txt
create_missing services < synthetic/services.txt
printf 'Created %s certificates (existing ones kept).\n' "$CREATED"

printf '\n[3/3] Broker ACL\n'
reload_broker_acl
