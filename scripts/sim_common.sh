# Gemeinsame Hilfsfunktionen fuer die Skripte 11-14 (per "." eingebunden, ROOT gesetzt).
# Standard: Python laeuft im Compose-Service "sim" (keine lokale Python-Installation noetig).
# SIM_LOCAL=1: stattdessen lokales python3 >= 3.11 mit paho-mqtt==2.1.0 (sim/requirements.txt);
# Broker dann ueber SIM_BROKER_HOST/SIM_BROKER_PORT (Standard localhost:8883).

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# No Docker "What's next / Gordon" hints after a non-zero exit (a failed acceptance is a result).
export DOCKER_CLI_HINTS=false

run_sim() {
  if [ "${SIM_LOCAL:-0}" = 1 ]; then
    PYTHONPATH="$ROOT/sim${PYTHONPATH:+:$PYTHONPATH}" python3 -m enetec_sim "$@"
  else
    # Build the local image once per script run (Docker cache makes repeats fast).
    # Plain "docker build -q" needs no console, unlike "docker compose build".
    if [ -z "${SIM_IMAGE_READY:-}" ]; then
      docker build -q -t enetec-sim:local "$ROOT/sim" >/dev/null ||
        die 'Building the sim image failed: docker build -t enetec-sim:local sim'
      SIM_IMAGE_READY=1
    fi
    docker compose run --rm -T sim "$@"
  fi
}

# Shell script inside the sim container (OpenSSL 3), or on the host with SIM_LOCAL=1.
# Used for the certificate scripts 12/15, whose "openssl ca" usage differs on LibreSSL.
run_script() {
  if [ "${SIM_LOCAL:-0}" = 1 ]; then
    "$ROOT/$1"
  else
    if [ -z "${SIM_IMAGE_READY:-}" ]; then
      docker build -q -t enetec-sim:local "$ROOT/sim" >/dev/null ||
        die 'Building the sim image failed: docker build -t enetec-sim:local sim'
      SIM_IMAGE_READY=1
    fi
    docker compose run --rm -T --entrypoint sh sim "$1"
  fi
}

# Compose service of the broker under test (broker = Lab-Mosquitto, emqx = EMQX).
BROKER_SERVICE="${BROKER_SERVICE:-broker}"

broker_running() {
  command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps -q "$BROKER_SERVICE" 2>/dev/null)" ]
}

broker_label() {
  if [ "$BROKER_SERVICE" = broker ] && broker_running; then
    VERSION=$(docker compose exec -T broker mosquitto -h 2>/dev/null | head -n 1)
    printf 'Mosquitto lab broker (%s)' "${VERSION:-version unknown}"
  else
    :   # not under Compose: the caller falls back to the profile name
  fi
}

# Broker-Log als Audit-Evidenz neben die Testergebnisse legen.
capture_broker_log() {
  if broker_running; then
    docker compose logs --no-color --since "$1" "$BROKER_SERVICE" > "$2" 2>&1 || true
  else
    printf 'No Compose broker running; attach the broker log manually.\n' > "$2"
  fi
}

# Neue ACL ohne Neustart laden (SIGHUP wie in Test 09/10).
reload_broker_acl() {
  if [ "$BROKER_SERVICE" = broker ] && broker_running; then
    docker compose exec -T broker kill -HUP 1 && printf 'Broker ACL reloaded (SIGHUP).\n'
  else
    printf 'Broker not running under Compose: reload its ACL manually (SIGHUP) if needed.\n'
  fi
}
