#!/usr/bin/env sh
# Vergleich zweier Broker (ENTC-59): make compare A=emqx B=mosquitto-lab
#   FRESH=1   Abnahme fuer beide Broker zuerst neu ausfuehren (sonst: letzter vollstaendiger Lauf je Broker)
#   Profile:  make brokers
# Ausgabe: results/compare-<A>-vs-<B>-<zeit>/ comparison.md, comparison.json, summary.txt
# Endet mit einer Zusammenfassung. Exit 0, wenn der Vergleich erstellt wurde (unabhaengig vom Abnahmeergebnis).
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/sim_common.sh"

A="${A:-}"
B="${B:-}"
if [ -z "$A" ] || [ -z "$B" ]; then
  printf 'Usage: make compare A=<broker> B=<broker> [FRESH=1]\n\nAvailable brokers (sim/targets/):\n'
  ls sim/targets/*.toml | sed 's#sim/targets/#  #; s#\.toml##'
  printf '\nLatest complete acceptance runs per broker:\n'
  for F in results/acceptance-*/report.json; do
    [ -f "$F" ] || continue
    printf '  %s\n' "$(sed -n 's/^  "profile": "\(.*\)",/\1/p;s/^  "run_id": "\(.*\)",/\1/p' "$F" | tr '\n' ' ')"
  done 2>/dev/null | tail -8
  exit 2
fi
[ "$A" != "$B" ] || die 'Choose two different brokers.'
for X in "$A" "$B"; do
  [ -f "sim/targets/$X.toml" ] || die "Unknown broker profile: $X (list: make brokers)"
done

if [ "${FRESH:-0}" = 1 ]; then
  for X in "$A" "$B"; do
    printf '\n=== Acceptance run: %s ===\n' "$X"
    # Acceptance exit code 1 (not accepted) is a result, not an error here.
    SIM_TARGET="sim/targets/$X.toml" ./scripts/13_acceptance.sh | sed -n '/^SUMMARY/,$p' || true
  done
fi
printf '\n'
run_sim compare "$A" "$B"
