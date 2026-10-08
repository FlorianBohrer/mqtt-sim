#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/poc_wire_check.sh"

GW="gw-sim-000001"
TOPIC="eicp/v1/sim/plt_sim_001/gateways/$GW/d2c/telemetry/report"

docker compose run --rm client   "mosquitto_pub     -h broker -p 8883     --cafile /certs/ca/ca.crt     --cert /certs/gateways/$GW/gateway.crt     --key /certs/gateways/$GW/gateway.key     -i $GW     -t '$TOPIC'     -q 1     -f /samples/telemetry.json     -d"
