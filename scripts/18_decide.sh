#!/usr/bin/env sh
# Gewichtete Entscheidungsmatrix (ENTC-59): make decide
# Liest sim/decision.toml (Gewichte, Kandidaten, belegte Handbewertungen) und den jeweils letzten
# vollstaendigen Acceptance-Lauf je Broker-Profil. Offene Kriterien zaehlen nicht als 0.
# Ausgabe: results/decision-<zeit>/ decision.md, decision.json, summary.txt
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/sim_common.sh"
run_sim decide
