#!/usr/bin/env sh
# Broker keystore for HiveMQ (PKCS#12) from the lab broker certificate.
# Runs in the sim container (OpenSSL 3) via scripts/sim_run.sh; output certs/hivemq/broker.p12.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"
[ -r certs/broker/broker.key ] || { echo 'certs/broker missing: run make init' >&2; exit 1; }
mkdir -p certs/hivemq
openssl pkcs12 -export -name broker -inkey certs/broker/broker.key -in certs/broker/broker.crt \
  -certfile certs/ca/ca.crt -out certs/hivemq/broker.p12 -passout pass:enetec-lab
chmod 644 certs/hivemq/broker.p12   # read by the HiveMQ container user (lab only)
echo "certs/hivemq/broker.p12 written"
