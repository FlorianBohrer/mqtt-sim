#!/usr/bin/env sh
# ENTC-63 Acceptance-Harness: ein Befehl, Exit 0 nur wenn ALLE Pflichtfaelle PASS sind.
#
# Baut fehlende Voraussetzungen selbst auf (Lab-CA, synthetische Flotte mit Zertifikaten,
# Negativ-Identitaeten), startet den Compose-Broker falls noetig, fuehrt alle Faelle aus
# (MTLS, ID, DUP, ACL, QOS, SES, REC), sammelt das Broker-Log des Laufs (LOG) und
# erzeugt report.md / report.json mit PASS/FAIL je Anforderung.
#
#   make acceptance                         Lab-Broker (Docker Compose, Profil mosquitto-lab)
#   make acceptance BROKER=emqx SIM_BROKER_LOG=<exportiertes-log>
#                                           anderer Broker; Einstellungen im Profil
#                                           sim/targets/<BROKER>.toml (Liste: make brokers)
#   SIM_BROKER_HOST / SIM_BROKER_PORT       ueberschreiben Host/Port des Profils
#   SIM_LOCAL=1                             lokales python3 statt sim-Container
#
# Reproduzierbar aus sauberem Stand: make clean && make acceptance
# Verwendet die ClientIDs der Flotte mit frischen Sessions: parallel laufende Clients
# (make simulate, Tests 09/10) vorher stoppen.
# Evidenz: results/acceptance-<RUN_ID>/ report.md, report.json, results.json, events.jsonl, broker.log
# Exit: 0 = alle Pflichtfaelle PASS; 1 = mindestens ein Pflichtfall FAIL/PARTIAL/INCONCLUSIVE.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/sim_common.sh"
TARGET="${SIM_TARGET:-sim/targets/mosquitto-lab.toml}"
[ -f "$TARGET" ] || die "Target profile not found: $TARGET"

printf '[1/5] Test PKI and synthetic fleet\n'
[ -r certs/ca/ca.key ] || ./scripts/01_create_ca_and_broker.sh >/dev/null 2>&1 || die 'CA creation failed.'
./scripts/11_synthetic_fleet.sh >/dev/null || die 'Fleet generation failed.'
for CERT in certs/gateways/*/gateway.crt certs/services/*/gateway.crt; do
  openssl verify -CAfile certs/ca/ca.crt "$CERT" >/dev/null 2>&1 ||
    die "$CERT does not chain to the current lab CA. Run: make clean && make acceptance"
done
# Negative identities are cheap: always re-issue them from the current CA.
./scripts/12_create_negative_identities.sh >/dev/null || die 'Negative identities failed.'
printf 'CA, %s gateway and %s service certificates, negative identities: OK\n' \
  "$(wc -l < synthetic/gateways.txt | tr -d ' ')" "$(wc -l < synthetic/services.txt | tr -d ' ')"

printf '\n[2/5] Broker\n'
PROFILE_NAME=$(sed -n 's/^name = "\(.*\)"/\1/p' "$TARGET")
if grep -q '^lab_managed = true' "$TARGET" && [ -z "${SIM_BROKER_HOST:-}" ] &&
   command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  broker_running || docker compose up -d broker
  WAITED=0
  until docker compose logs broker 2>/dev/null | grep -q 'running'; do
    [ "$WAITED" -lt 30 ] || die 'Lab broker did not start; see docker compose logs broker.'
    sleep 1
    WAITED=$((WAITED + 1))
  done
  printf 'Lab broker running (ACL loaded from mosquitto/config/acl).\n'
else
  printf 'Using %s from %s (not started by this script).\n' "$PROFILE_NAME" "$TARGET"
  grep -q '^status = "template"' "$TARGET" &&
    printf 'NOTE: profile status "template" - broker settings/log patterns not yet verified.\n'
fi

RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
START_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RESULTS="results/acceptance-$RUN_ID"
mkdir -p "$RESULTS"
if grep -q '^lab_managed = true' "$TARGET"; then LABEL="${BROKER_LABEL:-$(broker_label)}"
else LABEL="${BROKER_LABEL:-$PROFILE_NAME}"; fi

printf '\n[3/5] Acceptance cases\n'
run_sim acceptance --phase run --run-dir "$RESULTS" --target "$TARGET" || die 'Harness run failed.'

printf '\n[4/5] Broker log for the run window\n'
if [ -n "${SIM_BROKER_LOG:-}" ]; then
  cp "$SIM_BROKER_LOG" "$RESULTS/broker.log"
else
  capture_broker_log "$START_AT" "$RESULTS/broker.log"
fi
printf '%s\n' "$RESULTS/broker.log"

printf '\n[5/5] Report\n'
set +e
run_sim acceptance --phase report --run-dir "$RESULTS" --target "$TARGET" \
  --broker-log "$RESULTS/broker.log" --broker-label "$LABEL"
RC=$?
set -e
exit "$RC"
