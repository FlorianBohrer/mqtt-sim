#!/usr/bin/env sh
# Runs a lab script in the sim container (OpenSSL 3) or, with SIM_LOCAL=1, on the host.
# Usage: ./scripts/sim_run.sh scripts/12_create_negative_identities.sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/sim_common.sh"
[ "$#" -eq 1 ] && [ -f "$1" ] || die 'Usage: scripts/sim_run.sh <scripts/NN_name.sh>'
run_script "$1"
