#!/usr/bin/env sh
# ENTC-63 Acceptance-Harness: ein Befehl, Exit 0 nur wenn ALLE Pflichtfaelle PASS sind.
#
# Baut fehlende Voraussetzungen selbst auf (Lab-CA, synthetische Flotte mit Zertifikaten,
# Negativ-Identitaeten), startet den Compose-Broker falls noetig, fuehrt alle Faelle aus
# (MTLS, ID, DUP, ACL, QOS, SES, REC, LEG, ROT, PAY, LWT, EXP, RST, REV), sammelt das
# Broker-Log des Laufs (LOG) und erzeugt report.md / report.json mit PASS/FAIL je Anforderung.
#
#   make acceptance                         Lab-Broker (Docker Compose, Profil mosquitto-lab)
#   make acceptance BROKER=emqx SIM_BROKER_LOG=<exportiertes-log>
#                                           anderer Broker; Einstellungen im Profil
#                                           sim/targets/<BROKER>.toml (Liste: make brokers)
#   make acceptance WIRE=lab-eicp           frueheres Topic-/Client-ID-Profil (Standard: v13)
#   SIM_BROKER_HOST / SIM_BROKER_PORT       ueberschreiben Host/Port des Profils
#   SIM_LOCAL=1                             lokales python3 statt sim-Container
#
# Waehrend des Laufs fordert der Harness Broker-Aktionen an (Hooks: restart, revoke,
# acl-withdraw, acl-restore). Lab-Broker: docker compose bzw. Profil [hooks]. Externe Broker:
# SIM_HOOK_RESTART, SIM_HOOK_CRL_RELOAD, SIM_HOOK_ACL_RELOAD (Shell-Befehle); ohne sie bleiben
# RST-01, REV-01 und ACL-14 INCONCLUSIVE (beratend, aendern das Ergebnis nicht).
#
# Reproduzierbar aus sauberem Stand: make clean && make acceptance
# Verwendet die ClientIDs der Flotte mit frischen Sessions: parallel laufende Clients
# (make simulate, Tests 09/10) vorher stoppen.
# Evidenz: results/acceptance-<RUN_ID>/ report.md, report.json, results.json, events.jsonl, broker.log
# Exit: 0 = alle Pflichtfaelle PASS; 1 = mindestens ein Pflichtfall FAIL/PARTIAL/INCONCLUSIVE.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
. "$ROOT/scripts/sim_common.sh"
TARGET="${SIM_TARGET:-sim/targets/mosquitto-lab.toml}"
[ -f "$TARGET" ] || die "Target profile not found: $TARGET"

printf '[1/5] Test PKI and synthetic fleet\n'
[ -r certs/ca/ca.key ] || ./scripts/01_create_ca_and_broker.sh >/dev/null 2>&1 || die 'CA creation failed.'
./scripts/11_synthetic_fleet.sh >/dev/null || die 'Fleet generation failed.'
for CERT in certs/gateways/*/gateway.crt certs/services/*/gateway.crt; do
  openssl verify -CAfile certs/ca/ca.crt "$CERT" >/dev/null 2>&1 ||
    die "$CERT does not chain to the current lab CA. Run: make clean && make acceptance"
done
# Negative identities are cheap: always re-issue them from the current CA.
# Negative, legacy and rotation identities are created once and then kept: the broker under
# test (registry fingerprints, CRL) must keep matching them across runs. They are re-issued
# only if missing or if the lab CA changed (make init / make clean).
FIRST_LEGACY=$(head -n 1 synthetic/legacy_gateways.txt)
ROTATION_GW=$(sed -n 's/^rotation_gateway = "\(.*\)"/\1/p' sim/config.toml)
# revoke-live is revoked by REV-01 during a run: re-issue all negatives (fresh CRL) afterwards.
if [ ! -f certs/negative/crl.pem ] || [ ! -f certs/negative/revoke-live/client.crt ] ||
   [ -f certs/negative/revoke-live/.revoked ] ||
   ! openssl verify -CAfile certs/ca/ca.crt certs/negative/unknown-gateway/client.crt >/dev/null 2>&1; then
  OUT=$(run_script scripts/12_create_negative_identities.sh 2>&1) ||
    { printf '%s\n' "$OUT" >&2; die 'Negative identities failed.'; }
fi
if [ ! -f certs/legacy/registry.tsv ] ||
   ! openssl verify -CAfile certs/ca/ca.crt "certs/legacy/$FIRST_LEGACY/client.crt" >/dev/null 2>&1 ||
   ! openssl verify -CAfile certs/ca/ca.crt "certs/rotation/$ROTATION_GW/client.crt" >/dev/null 2>&1; then
  OUT=$(run_script scripts/15_create_legacy_identities.sh 2>&1) ||
    { printf '%s\n' "$OUT" >&2; die 'Legacy/rotation identities failed.'; }
fi
printf 'CA, %s gateway, %s service, %s legacy certificates, negative + rotation identities: OK\n' \
  "$(wc -l < synthetic/gateways.txt | tr -d ' ')" "$(wc -l < synthetic/services.txt | tr -d ' ')" \
  "$(wc -l < synthetic/legacy_gateways.txt | tr -d ' ')"

printf '\n[2/5] Broker\n'
PROFILE_NAME=$(sed -n 's/^name = "\(.*\)"/\1/p' "$TARGET")
BROKER_SERVICE=$(sed -n 's/^compose_service = "\(.*\)".*/\1/p' "$TARGET")
BROKER_SERVICE="${BROKER_SERVICE:-broker}"
READY_LOG=$(sed -n "s/^ready_log = '\(.*\)'.*/\1/p" "$TARGET")
COMPOSE_HOST=$(sed -n 's/^compose_host = "\(.*\)".*/\1/p' "$TARGET")
IMAGE_BUILD=$(sed -n 's/^image_build = "\(.*\)".*/\1/p' "$TARGET")
IMAGE=$(sed -n 's/^image = "\(.*\)".*/\1/p' "$TARGET")
PREPARE=$(sed -n 's/^prepare_script = "\(.*\)".*/\1/p' "$TARGET")
CRL_RELOAD=$(sed -n 's/^crl_reload = "\(.*\)".*/\1/p' "$TARGET")
ACL_RELOAD=$(sed -n 's/^acl_reload = "\(.*\)".*/\1/p' "$TARGET")
MANAGED=0

wait_ready() {   # $1: only log lines from this time on count
  WAITED=0
  until docker compose logs --since "$1" "$BROKER_SERVICE" 2>/dev/null | grep -Eq "${READY_LOG:-running}"; do
    [ "$WAITED" -lt 90 ] || return 1
    sleep 1
    WAITED=$((WAITED + 1))
  done
}
if grep -q '^lab_managed = true' "$TARGET" && [ -n "$COMPOSE_HOST" ]; then
  openssl x509 -in certs/broker/broker.crt -noout -text 2>/dev/null | grep -q "DNS:$COMPOSE_HOST" ||
    die "Broker certificate has no SAN \"$COMPOSE_HOST\" (older lab). Run: make clean && make acceptance BROKER=..."
fi
if [ -n "$PREPARE" ]; then
  OUT=$(run_script "$PREPARE" 2>&1) || { printf '%s\n' "$OUT" >&2; die "$PREPARE failed."; }
fi
if grep -q '^lab_managed = true' "$TARGET" && [ -z "${SIM_BROKER_HOST:-}" ] &&
   command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if [ -n "$IMAGE_BUILD" ]; then
    printf 'Building %s from %s (first run downloads the base images) ...\n' "$IMAGE" "$IMAGE_BUILD"
    docker build -q -t "$IMAGE" "$IMAGE_BUILD" >/dev/null || die "docker build -t $IMAGE $IMAGE_BUILD failed"
  fi
  # Always (re)create: the broker must load the certificates, registry and CRL of this run.
  STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  docker compose --profile "$BROKER_SERVICE" up -d --force-recreate "$BROKER_SERVICE" >/dev/null 2>&1 ||
    die "docker compose up $BROKER_SERVICE failed"
  sleep 2
  wait_ready "$STARTED" || die "Broker did not start; see docker compose logs $BROKER_SERVICE"
  MANAGED=1
  printf '%s running (compose service %s).\n' "$PROFILE_NAME" "$BROKER_SERVICE"
else
  printf 'Using %s from %s (not started by this script).\n' "$PROFILE_NAME" "$TARGET"
  grep -q '^status = "template"' "$TARGET" &&
    printf 'NOTE: profile status "template" - broker settings/log patterns not yet verified.\n'
fi

RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
START_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RESULTS="results/acceptance-$RUN_ID"
mkdir -p "$RESULTS"
# Only the Lab-Mosquitto is asked for its version; other brokers are labelled by their profile.
if [ "$BROKER_SERVICE" = broker ] && grep -q '^lab_managed = true' "$TARGET"; then
  LABEL="${BROKER_LABEL:-$(broker_label)}"
fi
LABEL="${LABEL:-${BROKER_LABEL:-$PROFILE_NAME}}"

# --- Hooks: broker actions the harness requests during the run (RST-01, REV-01, ACL-14) ---------
# Request <run>/hooks/<action>.request, answer <action>.done: ok | unsupported: ... | failed ...
reload_broker() {   # $1: crl | acl
  if [ "$1" = crl ]; then CUSTOM="${SIM_HOOK_CRL_RELOAD:-}" MODE="$CRL_RELOAD"
  else CUSTOM="${SIM_HOOK_ACL_RELOAD:-}" MODE="$ACL_RELOAD"; fi
  if [ -n "$CUSTOM" ]; then sh -c "$CUSTOM"; return; fi
  if [ "$MANAGED" != 1 ]; then
    echo "unsupported: broker not started by this script, set SIM_HOOK_$(printf %s "$1" | tr a-z A-Z)_RELOAD"
    return 3
  fi
  case "$MODE" in
    hup) docker compose exec -T "$BROKER_SERVICE" kill -HUP 1 ;;
    none) : ;;   # the broker picks up the changed file itself
    *) echo "unsupported: no $1_reload in $TARGET [hooks]"; return 3 ;;
  esac
}

run_hook() {   # $1: action, $2: request file
  case "$1" in
    restart)
      if [ -n "${SIM_HOOK_RESTART:-}" ]; then sh -c "$SIM_HOOK_RESTART"; return; fi
      [ "$MANAGED" = 1 ] || { echo 'unsupported: broker not started by this script, set SIM_HOOK_RESTART'; return 3; }
      SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      docker compose --profile "$BROKER_SERVICE" restart "$BROKER_SERVICE" && sleep 1 && wait_ready "$SINCE" ;;
    revoke) run_script scripts/17_revoke_live.sh && reload_broker crl ;;
    acl-withdraw)
      ID=$(sed -n 's/.*"identity": *"\([^"]*\)".*/\1/p' "$2")
      [ -n "$ID" ] || { echo 'no identity in the request'; return 1; }
      run_sim acl --withdraw "$ID" && reload_broker acl ;;
    acl-restore) run_sim acl && reload_broker acl ;;
    *) echo "unsupported: unknown hook $1"; return 3 ;;
  esac
}

hook_runner() {   # $1: run directory; ends when $1/hooks/stop exists
  while [ ! -f "$1/hooks/stop" ]; do
    for REQ in "$1"/hooks/*.request; do
      [ -f "$REQ" ] || continue
      ACTION=$(basename "$REQ" .request)
      mv "$REQ" "$REQ.taken"
      set +e
      (run_hook "$ACTION" "$REQ.taken") > "$1/hooks/$ACTION.log" 2>&1
      RC=$?
      set -e
      case "$RC" in
        0) ANSWER=ok ;;
        3) ANSWER=$(grep '^unsupported' "$1/hooks/$ACTION.log" | tail -n 1) ;;
        *) ANSWER="failed (exit $RC), see $1/hooks/$ACTION.log" ;;
      esac
      printf '           [hook %s: %s]\n' "$ACTION" "$ANSWER"
      printf '%s\n' "$ANSWER" > "$1/hooks/$ACTION.done"
    done
    sleep 0.5
  done
}

printf '\n[3/5] Acceptance cases\n'
mkdir -p "$RESULTS/hooks"   # created by the host: it must be able to answer in it
export SIM_HOOKS=1
hook_runner "$RESULTS" &
HOOK_PID=$!
trap 'touch "$RESULTS/hooks/stop" 2>/dev/null; kill "$HOOK_PID" 2>/dev/null || true' EXIT
run_sim acceptance --phase run --run-dir "$RESULTS" --target "$TARGET" || die 'Harness run failed.'
touch "$RESULTS/hooks/stop"
wait "$HOOK_PID" 2>/dev/null || true

printf '\n[4/5] Broker log for the run window\n'
if [ -n "${SIM_BROKER_LOG:-}" ]; then
  cp "$SIM_BROKER_LOG" "$RESULTS/broker.log"
else
  capture_broker_log "$START_AT" "$RESULTS/broker.log"
fi
printf '%s\n' "$RESULTS/broker.log"

printf '\n[5/5] Report\n'
set +e
run_sim acceptance --phase report --run-dir "$RESULTS" --target "$TARGET" \
  --broker-log "$RESULTS/broker.log" --broker-label "$LABEL"
RC=$?
set -e
exit "$RC"
