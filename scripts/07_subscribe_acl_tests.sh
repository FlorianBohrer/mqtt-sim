#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/poc_wire_check.sh"

GW="gw-sim-000001"

run_test() {
  NAME="$1"
  TOPIC="$2"

  echo
  echo "================================================"
  echo "$NAME"
  echo "Gateway: $GW"
  echo "Topic:   $TOPIC"
  echo "================================================"

  set +e

  docker compose run --rm client \
    "mosquitto_sub \
    -h broker \
    -p 8883 \
    --cafile /certs/ca/ca.crt \
    --cert /certs/gateways/$GW/gateway.crt \
    --key /certs/gateways/$GW/gateway.key \
    -V mqttv5 \
    -i $GW \
    -t '$TOPIC' \
    -q 1 \
    -W 3 \
    -d"

  RC=$?
  set -e

  echo "Client exit code: $RC"
}

run_test \
  "TEST 1 - Own gateway subscription - SHOULD ALLOW" \
  "eicp/v1/sim/plt_sim_001/gateways/gw-sim-000001/c2d/#"

run_test \
  "TEST 2 - Other gateway subscription - SHOULD DENY" \
  "eicp/v1/sim/plt_sim_002/gateways/gw-sim-000002/c2d/#"

run_test \
  "TEST 3 - Wildcard subscription - SHOULD DENY" \
  "eicp/v1/sim/+/gateways/+/c2d/#"

echo
echo "Broker log:"
docker compose logs --tail=80 broker
