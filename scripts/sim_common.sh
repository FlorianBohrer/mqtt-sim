# Gemeinsame Hilfsfunktionen fuer die Skripte 11-14 (per "." eingebunden, ROOT gesetzt).
# Standard: Python laeuft im Compose-Service "sim" (keine lokale Python-Installation noetig).
# SIM_LOCAL=1: stattdessen lokales python3 >= 3.11 mit paho-mqtt==2.1.0 (sim/requirements.txt);
# Broker dann ueber SIM_BROKER_HOST/SIM_BROKER_PORT (Standard localhost:8883).

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

run_sim() {
  if [ "${SIM_LOCAL:-0}" = 1 ]; then
    PYTHONPATH="$ROOT/sim${PYTHONPATH:+:$PYTHONPATH}" python3 -m enetec_sim "$@"
  else
    docker compose run --rm -T sim "$@"
  fi
}

broker_running() {
  command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps -q broker 2>/dev/null)" ]
}

broker_label() {
  if broker_running; then
    VERSION=$(docker compose exec -T broker mosquitto -h 2>/dev/null | head -n 1)
    printf 'Mosquitto lab broker (%s)' "${VERSION:-version unknown}"
  else
    printf 'broker at %s:%s' "${SIM_BROKER_HOST:-localhost}" "${SIM_BROKER_PORT:-8883}"
  fi
}

# Broker-Log als Audit-Evidenz neben die Testergebnisse legen.
capture_broker_log() {
  if broker_running; then
    docker compose logs --no-color --since "$1" broker > "$2" 2>&1 || true
  else
    printf 'No Compose broker running; attach the broker log manually.\n' > "$2"
  fi
}

# Neue ACL ohne Neustart laden (SIGHUP wie in Test 09/10).
reload_broker_acl() {
  if broker_running; then
    docker compose exec -T broker kill -HUP 1 && printf 'Broker ACL reloaded (SIGHUP).\n'
  else
    printf 'Broker not running under Compose: reload its ACL manually (SIGHUP) if needed.\n'
  fi
}
