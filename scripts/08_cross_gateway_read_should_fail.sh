#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/poc_wire_check.sh"

SNOOP_GW="gw-sim-000001"
PUB_GW="gw-sim-000002"

TOPIC="eicp/v1/sim/plt_sim_002/gateways/gw-sim-000002/d2c/telemetry/report"
PAYLOAD="ENETEC_CROSS_GATEWAY_SECRET_TEST"

run_test() {
  NAME="$1"
  FILTER="$2"
  CLIENT_ID="$3"

  OUT="$(mktemp)"

  echo
  echo "================================================"
  echo "$NAME"
  echo "Subscriber certificate: $SNOOP_GW"
  echo "Subscription:           $FILTER"
  echo "Publisher:              $PUB_GW"
  echo "Published topic:        $TOPIC"
  echo "================================================"

  set +e

  docker compose run --rm client \
    "mosquitto_sub \
    -h broker \
    -p 8883 \
    --cafile /certs/ca/ca.crt \
    --cert /certs/gateways/$SNOOP_GW/gateway.crt \
    --key /certs/gateways/$SNOOP_GW/gateway.key \
    -V mqttv5 \
    -i $CLIENT_ID \
    -t '$FILTER' \
    -q 1 \
    -C 1 \
    -W 5 \
    -v \
    -d" >"$OUT" 2>&1 &

  SUB_PID=$!

  set -e

  sleep 1

  echo
  echo "Publishing authorized message as $PUB_GW..."

  docker compose run --rm client \
    "mosquitto_pub \
    -h broker \
    -p 8883 \
    --cafile /certs/ca/ca.crt \
    --cert /certs/gateways/$PUB_GW/gateway.crt \
    --key /certs/gateways/$PUB_GW/gateway.key \
    -V mqttv5 \
    -i $PUB_GW \
    -t '$TOPIC' \
    -q 1 \
    -m '$PAYLOAD' \
    -d"

  set +e
  wait "$SUB_PID"
  SUB_RC=$?
  set -e

  echo
  echo "Subscriber output:"
  cat "$OUT"

  echo

  if grep -q "$PAYLOAD" "$OUT"; then
    echo "FAIL: Unauthorized gateway received the message."
    rm -f "$OUT"
    return 1
  else
    echo "PASS: Unauthorized gateway did NOT receive the message."
  fi

  echo "Subscriber exit code: $SUB_RC"

  rm -f "$OUT"
}

run_test \
  "TEST 1 - Cross-gateway READ" \
  "eicp/v1/sim/plt_sim_002/gateways/gw-sim-000002/d2c/#" \
  "gw-sim-000001-snoop-1"

run_test \
  "TEST 2 - Wildcard READ" \
  "eicp/v1/sim/+/gateways/+/d2c/#" \
  "gw-sim-000001-snoop-2"

echo
echo "Relevant broker logs:"
docker compose logs --tail=80 broker
