#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CERT="${1:-$ROOT/certs/gateways/gw-sim-000001/gateway.crt}"
openssl verify -CAfile "$ROOT/certs/ca/ca.crt" "$CERT"
