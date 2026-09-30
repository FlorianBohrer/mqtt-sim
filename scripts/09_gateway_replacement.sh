#!/usr/bin/env sh
# ENETEC simulation: temporary gateway replacement at the publish ACL layer.
# Run from the simulation project: sh scripts/09_gateway_replacement.sh
# Or: sh /path/to/09_gateway_replacement.sh /path/to/simulation-project
#
# Requires Docker Compose services broker/client; broker is Mosquitto PID 1,
# client has sh, timeout, mosquitto_pub and the existing /certs mount.
# Broker must use this ACL file and certificate CN as its ACL username
# (require_certificate true + use_identity_as_username true).
#
# Dedicated simulation only: temporarily replaces the WHOLE ACL with two users.
# Stop other simulation clients first: these probes reuse the gateway ClientIDs
# with fresh sessions and can displace existing clients / clear their sessions.
# Publishes synthetic, non-retained markers to the simulation telemetry topics.
# This changes no plant registry, certificate, firmware or physical gateway.
#
# Scope: PUBACK evidence for fresh connections; no delivery/read-isolation test,
# CRL/revocation test, active-connection termination or session migration test.
# ACLs are restored on normal exit and catchable signals. SIGKILL/power loss
# require manual recovery from the printed backup path. Do not edit ACLs mid-test.
# References: https://mosquitto.org/man/mosquitto-conf-5.html
#             https://mosquitto.org/man/mosquitto_pub-1.html
set -eu
umask 077
export LC_ALL=C

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die 'Usage: sh 09_gateway_replacement.sh [project-directory]'
if [ "$#" -eq 1 ]; then
  ROOT=$(CDPATH= cd -- "$1" && pwd)
elif [ -f mosquitto/config/acl ]; then
  ROOT=$(pwd)
else
  ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
fi
cd "$ROOT"
ACL="$ROOT/mosquitto/config/acl"
LOCK="$ROOT/mosquitto/config/.replacement-test-lock"
BACKUP="$LOCK/original-acl"
OLD_GW=gw-sim-000001
NEW_GW=gw-sim-000002
BASE=eicp/v1/sim/plt_sim_001/gateways
OLD_TOPIC="$BASE/$OLD_GW/d2c/telemetry/report"
NEW_TOPIC="$BASE/$NEW_GW/d2c/telemetry/report"
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
LOG_DIR="$ROOT/results/gateway-replacement-$RUN_ID"
CHANGED=0
TESTS_PASSED=0

command -v docker >/dev/null 2>&1 || die 'Docker is not installed or not on PATH.'
[ -f "$ACL" ] && [ -w "$ACL" ] || die "ACL missing or not writable: $ACL"
[ ! -L "$ACL" ] || die 'Use a regular ACL file, not a symlink.'
[ ! -e "$ROOT/mosquitto/config/acl.replacement-test-backup" ] ||
  die 'A backup from the earlier script exists. Resolve that recovery first.'
for CERT_FILE in certs/ca/ca.crt \
  "certs/gateways/$OLD_GW/gateway.crt" "certs/gateways/$OLD_GW/gateway.key" \
  "certs/gateways/$NEW_GW/gateway.crt" "certs/gateways/$NEW_GW/gateway.key"; do
  [ -r "$CERT_FILE" ] || die "Missing/unreadable certificate file: $CERT_FILE"
done
docker compose version >/dev/null
docker compose exec -T broker sh -c 'test "$(cat /proc/1/comm)" = mosquitto' ||
  die 'Expected a running Mosquitto process as broker PID 1.'
docker compose run --rm --no-deps -T --entrypoint sh client -c \
  'command -v mosquitto_pub >/dev/null && command -v timeout >/dev/null' ||
  die 'Client image must provide mosquitto_pub and timeout.'
mkdir -p "$LOG_DIR"
mkdir "$LOCK" 2>/dev/null || die "Another run or recovery is pending: $LOCK"

reload_acl() { docker compose exec -T broker kill -HUP 1; }

# All values below are passed as arguments, never interpolated into shell code.
# A missing PUBACK (including timeout, TLS or Docker failure) is never a pass.
probe() {
  PROBE_LABEL=$1
  PROBE_GW=$2
  PROBE_TOPIC=$3
  PROBE_LOG="$LOG_DIR/$PROBE_LABEL.log"
  PROBE_EXIT=0
  docker compose run --rm --no-deps -T --entrypoint sh client -c \
    'exec timeout 15 mosquitto_pub "$@"' sh \
    -h broker -p 8883 --cafile /certs/ca/ca.crt \
    --cert "/certs/gateways/$PROBE_GW/gateway.crt" \
    --key "/certs/gateways/$PROBE_GW/gateway.key" \
    -V mqttv5 -i "$PROBE_GW" -t "$PROBE_TOPIC" -q 1 \
    -m "SIMULATION_REPLACEMENT:$RUN_ID:$PROBE_LABEL" -d \
    >"$PROBE_LOG" 2>&1 || PROBE_EXIT=$?
  cat "$PROBE_LOG"
  printf 'Client exit code: %s\n' "$PROBE_EXIT" | tee -a "$PROBE_LOG"
}

has_puback() {
  # Mosquitto debug example: received PUBACK (Mid: 1, RC:135)
  grep -Eiq "received PUBACK.*RC:[[:space:]]*($1)([^0-9]|$)" "$PROBE_LOG"
}

record() {
  printf '%s\t%s\n' "$1" "$2" | tee -a "$LOG_DIR/summary.tsv"
}

assert_allow() {
  if [ "$PROBE_EXIT" -eq 0 ] && has_puback '0|16'; then
    record PASS "$PROBE_LABEL: publish authorized (RC 0 or 16)"
  else
    record FAIL "$PROBE_LABEL: expected successful PUBACK RC 0 or 16"
    return 1
  fi
}

assert_deny() {
  if has_puback 135; then
    record PASS "$PROBE_LABEL: publish denied (PUBACK RC 135)"
  else
    record FAIL "$PROBE_LABEL: expected PUBACK RC 135; connection failure is inconclusive"
    return 1
  fi
}

cleanup() {
  FINAL_EXIT=$?
  trap - 0
  trap '' HUP INT TERM
  set +e
  if [ "$CHANGED" -eq 1 ]; then
    printf '\nRestoring original ACL from %s\n' "$BACKUP"
    # In-place copy preserves the inode for single-file Docker bind mounts.
    if cp -p "$BACKUP" "$ACL" && cmp -s "$BACKUP" "$ACL" && reload_acl; then
      sleep 1
      probe 06_restored_old "$OLD_GW" "$OLD_TOPIC"
      if assert_allow; then
        record PASS 'Original ACL bytes restored; old gateway publish works again'
        rm -f "$BACKUP" "$LOCK/replacement-acl"
        rmdir "$LOCK"
      else
        FINAL_EXIT=1
      fi
    else
      record FAIL 'Original ACL restoration or reload failed'
      FINAL_EXIT=1
    fi
  else
    rm -f "$BACKUP" "$LOCK/replacement-acl"
    rmdir "$LOCK"
  fi
  if [ -d "$LOCK" ]; then
    printf 'RECOVERY REQUIRED. Keep backup: %s\n' "$BACKUP" >&2
    printf 'Restore original-acl to mosquitto/config/acl, reload broker, verify, then remove lock.\n' >&2
    FINAL_EXIT=1
  fi
  if [ "$FINAL_EXIT" -eq 0 ] && [ "$TESTS_PASSED" -eq 1 ]; then
    record PASS 'OVERALL: publish ACL replacement checks and restoration completed'
  else
    record FAIL 'OVERALL: test or cleanup incomplete; inspect logs'
    [ "$FINAL_EXIT" -ne 0 ] || FINAL_EXIT=1
  fi
  printf '\nEvidence: %s\n' "$LOG_DIR"
  printf 'Scope: fresh-connection publish authorization only. Other lifecycle tests remain open.\n'
  exit "$FINAL_EXIT"
}
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cp -p "$ACL" "$BACKUP"
printf 'Gateway replacement ACL simulation\nOld: %s\nNew: %s\nPlant: plt_sim_001\n' "$OLD_GW" "$NEW_GW"
printf 'Temporary WHOLE-ACL replacement. Backup: %s\nEvidence: %s\n' "$BACKUP" "$LOG_DIR"
printf 'check\tresult\n' > "$LOG_DIR/summary.tsv"
docker compose exec -T broker mosquitto -h > "$LOG_DIR/broker-version.log" 2>&1 || true

printf '\n[1/5] Old gateway is authorized before replacement\n'
probe 01_before_old "$OLD_GW" "$OLD_TOPIC"
assert_allow || exit 1

cat > "$LOCK/replacement-acl" <<ACL_EOF
# Temporary test ACL. Restored automatically after the test.
user $OLD_GW
topic deny #

user $NEW_GW
topic write $BASE/$NEW_GW/d2c/#
topic read $BASE/$NEW_GW/c2d/#
ACL_EOF
CHANGED=1
cat "$LOCK/replacement-acl" > "$ACL"
reload_acl
sleep 1

printf '\n[2/5] Old gateway is denied on its former topic after replacement\n'
probe 02_after_old "$OLD_GW" "$OLD_TOPIC"
assert_deny || exit 1

printf '\n[3/5] Replacement gateway is authorized on its own Plant 001 topic\n'
probe 03_after_new "$NEW_GW" "$NEW_TOPIC"
assert_allow || exit 1

printf '\n[4/5] Old gateway cannot publish under replacement identity\n'
probe 04_old_to_new "$OLD_GW" "$NEW_TOPIC"
assert_deny || exit 1

printf '\n[5/5] Replacement gateway cannot publish under old identity\n'
probe 05_new_to_old "$NEW_GW" "$OLD_TOPIC"
assert_deny || exit 1
TESTS_PASSED=1
# EXIT trap restores and verifies baseline before printing the overall result.
exit 0
