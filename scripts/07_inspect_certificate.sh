#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CERT="${1:-$ROOT/certs/gateways/gw-sim-000001/gateway.crt}"
openssl x509 -in "$CERT" -noout -text
echo
openssl x509 -in "$CERT" -noout -subject -issuer -serial -dates -fingerprint -sha256
