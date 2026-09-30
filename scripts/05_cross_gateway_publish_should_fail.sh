#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

AUTH_GW="gw-sim-000001"
TOPIC="eicp/v1/sim/plt_sim_002/gateways/gw-sim-000002/d2c/telemetry/report"

echo "Certificate identity: $AUTH_GW"
echo "Attempted topic:      $TOPIC"
echo "Expected: MQTT 5 Not Authorized."

set +e

docker compose run --rm client \
  "mosquitto_pub -h broker -p 8883 \
  --cafile /certs/ca/ca.crt \
  --cert /certs/gateways/$AUTH_GW/gateway.crt \
  --key /certs/gateways/$AUTH_GW/gateway.key \
  -V mqttv5 \
  -i $AUTH_GW \
  -t '$TOPIC' \
  -q 1 \
  -f /samples/telemetry.json \
  -d"

RC=$?

set -e

echo "Client exit code: $RC"
