#!/usr/bin/env sh
# Container start: truststore with the lab CA (keytool, ships with HiveMQ's JRE), then HiveMQ.
set -eu
TRUST="${ENETEC_TRUSTSTORE:-/opt/hivemq/data/enetec-truststore.p12}"
rm -f "$TRUST"
keytool -importcert -noprompt -alias enetec-lab-ca -file "${ENETEC_CA:-/opt/hivemq/lab-certs/ca/ca.crt}" \
  -keystore "$TRUST" -storetype PKCS12 -storepass enetec-lab >/dev/null
exec /opt/hivemq/bin/run.sh
