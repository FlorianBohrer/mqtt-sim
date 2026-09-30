#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

CERT_GW="gw-sim-000001"
WRONG_ID="gw-sim-999999"
TOPIC="eicp/v1/sim/plt_sim_001/gateways/$CERT_GW/d2c/telemetry/report"

echo "Certificate CN: $CERT_GW"
echo "MQTT Client ID: $WRONG_ID"
echo
echo "Target ENETEC rule:"
echo "certificate identity == MQTT Client ID == Gateway ID"
echo
echo "This Mosquitto lab maps CN -> authorization username but does not"
echo "automatically enforce CN == Client ID at CONNECT."
echo "A successful connection here demonstrates the broker-capability gap."

set +e
docker compose run --rm client   "mosquitto_pub     -h broker -p 8883     --cafile /certs/ca/ca.crt     --cert /certs/gateways/$CERT_GW/gateway.crt     --key /certs/gateways/$CERT_GW/gateway.key     -i $WRONG_ID     -t '$TOPIC'     -q 1     -f /samples/telemetry.json     -d"
RC=$?
set -e

echo "Client exit code: $RC"
echo "Inspect: docker compose logs --tail=100 broker"
