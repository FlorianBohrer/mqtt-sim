#!/usr/bin/env sh
# Architektur-Simulation: alle Gateways der synthetischen Flotte plus Cloud-Platzhalter
# (Ingest, Command) spielen den 24-h-Datensatz zeitgerafft gegen den Broker ab:
# QoS 1, MQTT 5, Netzabbrueche ohne DISCONNECT, Reconnect mit Clean Start = false,
# Offline-Puffer, Commands in die persistente Session. Danach Auswertung gegen den Plan.
# Voraussetzung: make init, make fleet, make up.
# Optionen: BROKER=<profil> (sim/targets/, Standard mosquitto-lab), SPEED=720 (24 h in 2 min),
#           GATEWAYS=gw-sim-000001,gw-sim-000006
# Evidenz: results/simulation-<RUN_ID>/ run.json, events.jsonl, report.json, summary.txt, broker.log
# Exit: 0 = PASS, 1 = FAIL, 2 = unklar (Lauf unvollstaendig).
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/sim_common.sh"

[ -f certs/services/svc-sim-cloud-ingest/gateway.crt ] || die 'Fleet certificates missing. Run make fleet first.'
TARGET="${SIM_TARGET:-sim/targets/mosquitto-lab.toml}"
[ -f "$TARGET" ] || die "Broker profile not found: $TARGET (list: make brokers)"
BROKER_SERVICE=$(sed -n 's/^compose_service = "\(.*\)".*/\1/p' "$TARGET")
BROKER_SERVICE="${BROKER_SERVICE:-broker}"
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
START_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RESULTS="results/simulation-$RUN_ID"
mkdir -p "$RESULTS"

set +e
if [ -n "${GATEWAYS:-}" ]; then
  run_sim simulate --run-dir "$RESULTS" --target "$TARGET" --speed "${SPEED:-720}" --gateways "$GATEWAYS"
else
  run_sim simulate --run-dir "$RESULTS" --target "$TARGET" --speed "${SPEED:-720}"
fi
RC=$?
set -e
capture_broker_log "$START_AT" "$RESULTS/broker.log"
printf 'Broker log: %s/broker.log\nExit code: %s (0=PASS, 1=FAIL, 2=inconclusive)\n' "$RESULTS" "$RC"
exit "$RC"
