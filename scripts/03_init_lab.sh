#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
"$ROOT/scripts/00_check_prerequisites.sh"
"$ROOT/scripts/01_create_ca_and_broker.sh"
"$ROOT/scripts/02_create_gateway.sh" gw-sim-000001
"$ROOT/scripts/02_create_gateway.sh" gw-sim-000002
echo "Lab initialized. Next: make up"
