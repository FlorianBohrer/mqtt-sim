#!/usr/bin/env sh
# Test 10: existing MQTT v5 connection during publish/read ACL withdrawal.
# Usage from enetec_mtls_lab: sh scripts/10_active_connection_acl.sh
# Optional: sh /path/to/10_active_connection_acl.sh /path/to/enetec_mtls_lab
#
# Dedicated simulation only. Stop other clients using gw-sim-000001/000002.
# The test uses these canonical ClientIDs, Clean Start=true and Session Expiry=0.
# It temporarily replaces the WHOLE ACL. Original content/mode are restored.
# Gateway 000002 temporarily acts as a command sender and delivery witness;
# these test permissions are NOT a proposed production gateway role.
# Only synthetic non-retained messages on /sim/ topics are published.
# No certificate is revoked and no production registry/plant data is changed.
#
# Dependencies: existing broker/client Compose services and certificates;
# Docker downloads python:3.12-alpine if missing and installs paho-mqtt==2.1.0
# in a disposable container. No Python installation on the Mac is needed.
# Certificates are mounted read-only; Docker socket is never mounted.
# Original gateway uses ONE MQTT connection for both publish and subscribe;
# automatic reconnect is disabled. It is never resubscribed after withdrawal.
# The control gateway reconnects to verify the new ACL has actually loaded.
# Missing messages count as blocked only with a working delivery witness and
# a post-withdrawal PINGRESP on the original connection. Observation: 12 seconds.
#
# Catchable signals trigger cleanup. SIGKILL, power/Docker loss may require
# recovery from the printed original-acl backup. Do not edit ACL during the run.
# Exit 0: access blocked, original connection remained open, cleanup passed.
# Exit 1: unauthorized access observed or cleanup/setup failed.
# Exit 2: result inconclusive (including a closed connection needing review).
# Evidence: summary.txt, report.json, events.jsonl, broker.log, restoration.log.
# Paho API reference: https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html
# Lesefaden: Die Shell verwaltet Docker, ACL-Dateien und Wiederherstellung.
# Der eingebettete Python-Teil haelt die MQTT-Verbindungen offen und misst.
# Gegenstand ist der Entzug von Topic-Rechten auf einer bestehenden Verbindung.
# Zertifikatswiderruf und ein erzwungener Disconnect werden hier nicht ausgeloest.

# Bei Fehlern normalerweise abbrechen; nicht gesetzte Variablen sind Fehler.
# Neu angelegte Ergebnisdateien sind standardmaessig nur fuer den Besitzer lesbar.
set -eu
umask 077
export LC_ALL=C
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die 'Usage: sh 10_active_connection_acl.sh [project-directory]'
if [ "$#" -eq 1 ]; then
  ROOT=$(CDPATH= cd -- "$1" && pwd)
elif [ -f mosquitto/config/acl ]; then
  ROOT=$(pwd)
else
  ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
fi
cd "$ROOT"
ACL="$ROOT/mosquitto/config/acl"
# Gemeinsame Sperre mit Test 09: Zwei Tests duerfen nicht gleichzeitig die
# gesamte ACL ersetzen, sonst koennte einer das Backup des anderen ueberschreiben.
LOCK="$ROOT/mosquitto/config/.replacement-test-lock"
BACKUP="$LOCK/original-acl"
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
START_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RESULTS="$ROOT/results/active-connection-$RUN_ID"
COMMAND="eicp/v1/sim/plt_sim_001/gateways/gw-sim-000001/c2d/simulation/test10/$RUN_ID"
TELEMETRY=eicp/v1/sim/plt_sim_001/gateways/gw-sim-000001/d2c/telemetry/report
# Erst vor dem ersten ACL-Schreibzugriff auf 1 setzen. Damit weiss cleanup(),
# ob es die Originaldatei auch bei einem teilweise fehlgeschlagenen Schreiben
# wiederherstellen muss.
CHANGED=0
CONTAINER_ID=

command -v docker >/dev/null 2>&1 || die 'Docker is not available.'
[ -f "$ACL" ] && [ -w "$ACL" ] && [ ! -L "$ACL" ] || die 'ACL must be a writable regular file.'
[ ! -e mosquitto/config/acl.replacement-test-backup ] || die 'Resolve the old Test 09 backup first.'
for CERT in certs/ca/ca.crt \
  certs/gateways/gw-sim-000001/gateway.crt certs/gateways/gw-sim-000001/gateway.key \
  certs/gateways/gw-sim-000002/gateway.crt certs/gateways/gw-sim-000002/gateway.key; do
  [ -r "$CERT" ] || die "Missing certificate file: $CERT"
done
docker compose version >/dev/null
docker compose exec -T broker sh -c 'test "$(cat /proc/1/comm)" = mosquitto' ||
  die 'Expected a running Mosquitto broker as PID 1.'
docker compose run --rm --no-deps -T --entrypoint sh client -c \
  'command -v mosquitto_pub >/dev/null && command -v timeout >/dev/null' ||
  die 'Existing client image must provide mosquitto_pub and timeout.'
BROKER_ID=$(docker compose ps -q broker)
[ -n "$BROKER_ID" ] || die 'No running broker container.'
NETWORK_INFO=$(docker inspect -f '{{range $n,$v := .NetworkSettings.Networks}}{{$n}} {{$v.IPAddress}}{{"\n"}}{{end}}' "$BROKER_ID" | head -n 1)
NETWORK=$(printf '%s\n' "$NETWORK_INFO" | awk '{print $1}')
BROKER_IP=$(printf '%s\n' "$NETWORK_INFO" | awk '{print $2}')
[ -n "$NETWORK" ] && [ -n "$BROKER_IP" ] || die 'Expected broker on a Docker bridge network with an IPv4 address.'
mkdir -p "$RESULTS"
# mkdir ist hier zugleich die Sperrpruefung: Existiert der Ordner bereits,
# wird abgebrochen. Ein Backup eines vorherigen Laufs bleibt dadurch erhalten.
mkdir "$LOCK" 2>/dev/null || die "Another test or recovery is pending: $LOCK"

# SIGHUP fordert Mosquitto zum Neuladen auf, ohne den Broker neu zu starten.
# Ein Neustart wuerde die untersuchte bestehende Verbindung selbst zerstoeren.
# Dass die neue ACL wirklich gilt, prueft spaeter der ACL_GENERATION-Marker.
reload_acl() { docker compose exec -T broker kill -HUP 1; }

cleanup() {
# Den urspruenglichen Teststatus zuerst sichern. Danach EXIT-Trap abschalten,
# damit das abschliessende exit cleanup() nicht erneut aufruft. set +e sorgt
# dafuer, dass ein Aufraeumfehler weitere Wiederherstellungsversuche nicht stoppt.
  FINAL_EXIT=$?
  trap - 0
  trap '' HUP INT TERM
  set +e
  CLEAN_OK=1
  if [ -n "$CONTAINER_ID" ]; then
    docker logs "$CONTAINER_ID" > "$RESULTS/runner.log" 2>&1
    # Nur den eigenen Testcontainer entfernen. Dadurch sind seine MQTT-Clients
    # beendet, bevor die Wiederherstellungspruefung dieselbe ClientID verwendet.
    docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || CLEAN_OK=0
  fi
  if [ "$CHANGED" -eq 1 ]; then
    printf '\nRestoring original ACL...\n'
# Originaldaten und Dateirechte zurueckkopieren, Dateiinhalte vergleichen und
# neu laden. Anschliessend muss ein frischer Publish mit der alten Identitaet
# funktionieren: Eine vorhandene Datei allein beweist noch keine wirksame ACL.
    if cp -p "$BACKUP" "$ACL" && cmp -s "$BACKUP" "$ACL" && reload_acl; then
      sleep 1
      RESTORE_RC=0
      docker compose run --rm --no-deps -T --entrypoint sh client -c \
        'exec timeout 15 mosquitto_pub "$@"' sh \
        -h broker -p 8883 --cafile /certs/ca/ca.crt \
        --cert /certs/gateways/gw-sim-000001/gateway.crt \
        --key /certs/gateways/gw-sim-000001/gateway.key \
        -V mqttv5 -i gw-sim-000001 -q 1 -t "$TELEMETRY" \
        -m "$RUN_ID:RESTORATION_CHECK" -d > "$RESULTS/restoration.log" 2>&1 || RESTORE_RC=$?
      # Der Prozess-Exitcode allein reicht nicht: In Test 09 lieferte auch ein
      # abgewiesener Publish Exit 0. Deshalb zusaetzlich den PUBACK auswerten.
      # RC 0 = angenommen; RC 16 = angenommen, aber kein passender Subscriber.
      if [ "$RESTORE_RC" -eq 0 ] && grep -Eiq 'received PUBACK.*RC:[[:space:]]*(0|16)([^0-9]|$)' "$RESULTS/restoration.log"; then
        printf 'PASS: original ACL bytes/mode restored; original gateway publish works.\n' | tee "$RESULTS/cleanup.txt"
      else
        printf 'FAIL: restored ACL could not be verified.\n' | tee "$RESULTS/cleanup.txt"
        cat "$RESULTS/restoration.log"
        CLEAN_OK=0
      fi
    else
      printf 'FAIL: ACL restoration or reload failed.\n' | tee "$RESULTS/cleanup.txt"
      CLEAN_OK=0
    fi
  fi
  docker compose logs --no-color --since "$START_AT" broker > "$RESULTS/broker.log" 2>&1 || true
# Backup und Sperre erst nach erfolgreichem Aufraeumen entfernen. Bei einem
# Fehler waehrend der Wiederherstellung bleibt das Original fuer Recovery liegen.
  if [ "$CLEAN_OK" -eq 1 ]; then
    for TEMP in "$BACKUP" "$LOCK/baseline-acl" "$LOCK/withdrawn-acl"; do
      if [ -f "$TEMP" ]; then rm "$TEMP" || CLEAN_OK=0; fi
    done
    rmdir "$LOCK" || CLEAN_OK=0
  fi
  if [ "$CLEAN_OK" -ne 1 ]; then
    printf 'RECOVERY REQUIRED: %s\n' "$BACKUP" >&2
    printf 'Restore original-acl to mosquitto/config/acl, reload, verify, then remove the lock.\n' >&2
    printf 'Disposable container (if removal failed): %s\n' "$CONTAINER_ID" >&2
    FINAL_EXIT=1
  fi
  printf '\nEvidence: %s\n' "$RESULTS"
  printf 'Exit code: %s (0=access blocked/connection open; 1=failure; 2=inconclusive).\n' "$FINAL_EXIT"
  exit "$FINAL_EXIT"
}
# EXIT und abfangbare Abbruchsignale fuehren durch cleanup(). SIGKILL und ein
# Rechnerausfall koennen diesen Schutz umgehen; dafuer gibt es das ACL-Backup.
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
cp -p "$ACL" "$BACKUP"
printf 'TEST 10: active gateway connection during ACL withdrawal\n'
printf 'Backup: %s\nEvidence: %s\n' "$BACKUP" "$RESULTS"
printf 'Temporary whole-ACL change; gateway 000002 is a test command sender.\n'

# Der zitierte Here-Document-Begrenzer verhindert, dass die Shell Variablen
# oder Sonderzeichen des folgenden Python-Codes vorzeitig interpretiert.
cat > "$RESULTS/probe.py" <<'PYTHON_WORKER'
"""Test 10 worker, embedded by the .sh wrapper. Requires paho-mqtt==2.1.0.

Uses one non-reconnecting old-gateway connection for publish AND subscribe.
The second gateway is a temporary command publisher / delivery witness only.
"""
import json
import os
from pathlib import Path
import threading
import time
import traceback
import paho.mqtt.client as mqtt

WORK = Path(os.environ.get('TEST_WORK', '/work'))
CERTS = Path(os.environ.get('TEST_CERTS', '/certs'))
HOST = os.environ.get('TEST_BROKER_HOST', 'broker')
PORT = int(os.environ.get('TEST_BROKER_PORT', '8883'))
RUN = os.environ['TEST_RUN_ID']
OLD = 'gw-sim-000001'
CONTROL = 'gw-sim-000002'
BASE = 'eicp/v1/sim/plt_sim_001/gateways/' + OLD
TELEMETRY = BASE + '/d2c/telemetry/report'
COMMAND = BASE + '/c2d/simulation/test10/' + RUN
GENERATION = COMMAND + '/acl-generation'
# Eindeutiges Topic und eindeutige Payloads pro Lauf vermeiden Verwechslungen
# mit frueheren Tests. Die Beobachtung ist zeitlich begrenzt: 12 Sekunden sind
# kein Nachweis dafuer, dass eine Nachricht niemals spaeter eintreffen koennte.
OBSERVE = 12
WRITE_LOCK = threading.Lock()
START = time.monotonic()


def event(kind, **data):
    record = {'elapsed_s': round(time.monotonic()-START, 3), 'event': kind, **data}
    line = json.dumps(record, sort_keys=True)
    # Callbacks laufen in Paho-Netzwerkthreads, die Messsteuerung im Hauptthread.
    # Das Lock verhindert ineinander geschriebene JSON-Zeilen im Beweisprotokoll.
    with WRITE_LOCK:
        with (WORK/'events.jsonl').open('a') as f:
            f.write(line + '\n')
        print(line, flush=True)


def wait_until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def require(condition, description):
    if not condition:
        raise RuntimeError(description)
    event('check_pass', check=description)


class Gateway:
    def __init__(self, identity):
        self.identity = identity
        self.connects = 0
        self.connack = None
        self.closed = []
        self.acks = {}
        self.subacks = {}
        self.messages = set()
        self.last_ping = 0.0
        self.cleaning_up = False
        # Dieselbe Client-Instanz publiziert UND abonniert. Zwei getrennte
        # Clients mit derselben ClientID koennten sich gegenseitig verdraengen.
        # Kein Auto-Reconnect: Nach einem Verbindungsabbruch darf keine neue
        # Verbindung unbemerkt als die urspruengliche gemessen werden.
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=identity, protocol=mqtt.MQTTv5,
                                  reconnect_on_failure=False)
        self.client.connect_timeout = 8
        # mTLS: CA zur Brokerpruefung, individuelles Zertifikat und privater
        # Schluessel zur Client-Authentisierung. Diese Dateien werden nur gelesen;
        # es wird weder eine CRL eingerichtet noch ein Zertifikat widerrufen.
        self.client.tls_set(ca_certs=str(CERTS/'ca/ca.crt'),
                            certfile=str(CERTS/'gateways'/identity/'gateway.crt'),
                            keyfile=str(CERTS/'gateways'/identity/'gateway.key'))
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_publish = self.on_publish
        self.client.on_subscribe = self.on_subscribe
        self.client.on_message = self.on_message
        self.client.on_log = self.on_log

    def on_connect(self, client, userdata, flags, reason, props):
        # Fuer das alte Gateway muss dieser Zaehler waehrend der Messung 1 bleiben.
        self.connects += 1
        self.connack = reason.value
        event('connack', gateway=self.identity, code=reason.value,
              count=self.connects, session_present=flags.session_present)

    def on_disconnect(self, client, userdata, flags, reason, props):
        # Ein MQTT-DISCONNECT vom Server und ein Transportabbruch sind getrennte
        # Beobachtungen. cleanup markiert absichtlich vom Test geschlossene Clients.
        details = {'code': reason.value, 'reason': str(reason),
                   'server_disconnect_packet': flags.is_disconnect_packet_from_server,
                   'cleanup': self.cleaning_up}
        self.closed.append(details)
        event('connection_closed', gateway=self.identity, **details)

    def on_publish(self, client, userdata, mid, reason, props):
        # QoS 1: Die Brokerantwort wird der Message-ID zugeordnet. Ein erfolgreich
        # aufgerufener publish() bedeutet nur, dass der Client senden konnte;
        # erst dieser PUBACK zeigt Annahme oder Ablehnung durch den Broker.
        self.acks[mid] = reason.value
        event('puback', gateway=self.identity, mid=mid, code=reason.value)

    def on_subscribe(self, client, userdata, mid, reasons, props):
        # SUBACK bestaetigt das Abonnement. Die tatsaechliche Leseberechtigung
        # wird separat ueber den Empfang eindeutiger Testnachrichten gemessen.
        self.subacks[mid] = [r.value for r in reasons]
        event('suback', gateway=self.identity, mid=mid, codes=self.subacks[mid])

    def on_message(self, client, userdata, msg):
        text = msg.payload.decode('utf-8', errors='replace')
        self.messages.add((msg.topic, text))
        event('message_received', gateway=self.identity, topic=msg.topic,
              payload=text, retained=bool(msg.retain))

    def on_log(self, client, userdata, level, text):
        # Ein frischer PINGRESP belegt einen MQTT-Antwortverkehr nach dem Entzug.
        # Nur ein laufender Prozess oder is_connected() waere zu wenig Evidenz.
        if 'Received PINGRESP' in text:
            self.last_ping = time.monotonic()
            event('ping_response', gateway=self.identity)

    def open(self):
        # Frischer Testzustand; keine alten Abonnements oder Offline-Nachrichten
        # uebernehmen. Session Expiry bleibt beim MQTT-5-Standardwert 0.
        # Keepalive 5 s beschleunigt die Messung und ist kein Produktionsvorschlag.
        self.client.connect(HOST, PORT, keepalive=5, clean_start=True)
        self.client.loop_start()
        require(wait_until(lambda: self.connack is not None), self.identity+' CONNACK received')
        require(self.connack == 0, self.identity+' connection accepted')

    def subscribe(self, topics):
        rc, mid = self.client.subscribe([(topic, 1) for topic in topics])
        require(rc == mqtt.MQTT_ERR_SUCCESS, self.identity+' SUBSCRIBE queued')
        require(wait_until(lambda: mid in self.subacks), self.identity+' SUBACK received')
        require(all(code < 128 for code in self.subacks[mid]), self.identity+' subscription accepted')

    def publish(self, topic, payload):
        # Nicht-retained, damit diese Testmarker nicht fuer spaetere Subscriber
        # gespeichert werden. Ein fehlender PUBACK bleibt None, kein ACL-Erfolg.
        info = self.client.publish(topic, payload, qos=1, retain=False)
        event('publish_attempt', gateway=self.identity, topic=topic,
              payload=payload, mid=info.mid, client_rc=int(info.rc))
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return None
        wait_until(lambda: info.mid in self.acks or bool(self.closed))
        return self.acks.get(info.mid)

    def close(self):
        self.cleaning_up = True
        self.client.disconnect()
        self.client.loop_stop()


def classify(puback, post_delivered, connected, fresh_ping, closed, connects):
    """A timeout or disappeared client must never be reported as ACL success."""
    # Drei getrennte Aussagen: Darf der Client publizieren? Wird ein Command
    # zugestellt? Besteht die Verbindung noch? Ein Verbindungsabbruch allein
    # beweist keine wirksame ACL auf einer weiterhin offenen Verbindung.
    if connects != 1:
        return {'overall': 'INCONCLUSIVE: original connection was not preserved', 'exit': 2}
    # RC 135 ist die konkrete Autorisierungsablehnung. Timeout, andere Codes
    # oder fehlende Antworten sind unklar und duerfen nicht als PASS gelten.
    publication = ('BLOCKED_PUBACK_135' if puback == 135 else
                   'FAIL_STILL_AUTHORIZED' if puback in (0, 16) else
                   'INCONCLUSIVE_NO_135_PUBACK')
    connection = ('OPEN_PINGRESP_VERIFIED' if connected and fresh_ping and not closed else
                  'CLOSED_OBSERVED' if closed and not connected else 'INCONCLUSIVE')
    # Der Aufrufer hat die Zustellung an den Kontrollclient bereits bestaetigt.
    # Erst zusammen mit der lebenden Altverbindung ist ein ausbleibender Empfang
    # ein belastbarer Befund fuer dieses Topic und dieses Beobachtungsfenster.
    delivery = ('FAIL_COMMAND_DELIVERED' if post_delivered else
                'BLOCKED_OBSERVED_12_SECONDS' if connection == 'OPEN_PINGRESP_VERIFIED' else
                'NOT_TESTABLE_CONNECTION_CLOSED' if connection == 'CLOSED_OBSERVED' else
                'INCONCLUSIVE')
    if publication.startswith('FAIL') or delivery.startswith('FAIL'):
        overall, code = 'FAIL: access remained after withdrawal', 1
    # PASS bezieht sich hier auf den Rechteentzug. CONNECTION_REMAINED_OPEN
    # bleibt als eigener Befund sichtbar; erzwungene Trennung ist nicht bewiesen.
    elif publication == 'BLOCKED_PUBACK_135' and delivery == 'BLOCKED_OBSERVED_12_SECONDS':
        overall, code = 'PASS_ACCESS_BLOCKED; CONNECTION_REMAINED_OPEN', 0
    elif connection == 'CLOSED_OBSERVED':
        overall, code = 'CONNECTION_CLOSED; active ACL checks incomplete, inspect cause', 2
    else:
        overall, code = 'INCONCLUSIVE: inspect packet and connection evidence', 2
    return {'publish_after_withdrawal': publication,
            'command_delivery_after_withdrawal': delivery,
            'connection_after_withdrawal': connection, 'overall': overall, 'exit': code}


def main():
    old = control = None
    result = {'overall': 'INCONCLUSIVE', 'exit': 2}
    try:
        # Die Dateien synchronisieren Host-Shell und Container: Erst wenn die
        # Bibliothek geladen und die Baseline-ACL installiert ist, verbinden.
        (WORK/'dependencies_ready').touch()
        require(wait_until(lambda: (WORK/'start_baseline').exists(), 90), 'baseline ACL ready')
        old = Gateway(OLD)
        control = Gateway(CONTROL)
        old.open()
        control.open()
        old.subscribe([COMMAND])
        control.subscribe([COMMAND, TELEMETRY])
        # Positivkontrolle VOR dem Entzug: Beide Datenrichtungen muessen real
        # funktionieren. Sonst koennte ein grundsaetzlich defekter Aufbau spaeter
        # faelschlich als erfolgreiche Zugriffssperre erscheinen.
        baseline_telemetry = RUN+':BEFORE_TELEMETRY'
        baseline_command = RUN+':BEFORE_COMMAND'
        require(old.publish(TELEMETRY, baseline_telemetry) in (0, 16), 'baseline old publish authorized')
        require(wait_until(lambda: (TELEMETRY, baseline_telemetry) in control.messages),
                'baseline telemetry delivered to control client')
        require(control.publish(COMMAND, baseline_command) in (0, 16), 'baseline command authorized')
        require(wait_until(lambda: (COMMAND, baseline_command) in old.messages and
                           (COMMAND, baseline_command) in control.messages),
                'baseline command delivered to both clients')
        require(old.client.is_connected() and not old.closed and old.connects == 1,
                'original old gateway connection open before withdrawal')
        event('request_acl_withdrawal')
        # Ab hier darf die Shell umstellen. Das alte Gateway wird dabei weder
        # getrennt noch erneut abonniert; Pahos Netzwerkthread laeuft weiter.
        (WORK/'withdraw_request').touch()
        require(wait_until(lambda: (WORK/'withdrawal_done').exists(), 90), 'withdrawal signal received')

        # Nur den Kontrollclient neu verbinden. Sein Marker-Topic war in der
        # Baseline nicht freigegeben und wird erst in der neuen ACL erlaubt.
        # Der erfolgreiche Marker-Publish prueft damit die wirksame Umstellung;
        # ein gesendetes SIGHUP oder sleep(1) allein waere dafuer kein Nachweis.
        control.close()
        control = Gateway(CONTROL)
        control.open()
        control.subscribe([COMMAND, TELEMETRY])
        require(control.publish(GENERATION, RUN+':ACL_GENERATION') in (0, 16),
                'fresh control connection sees newly granted ACL permission')
        require(old.connects == 1, 'old gateway has not reconnected')
        # Diesen Publish sendet die bereits vor dem Entzug geoeffnete Verbindung.
        post_puback = old.publish(TELEMETRY, RUN+':AFTER_TELEMETRY')
        after_command = RUN+':AFTER_COMMAND'
        command_sent_at = time.monotonic()
        require(control.publish(COMMAND, after_command) in (0, 16), 'post-withdrawal command accepted')
        # Der Kontrollclient abonniert dasselbe Command-Topic. Sein Empfang
        # bestaetigt, dass die Nachricht angenommen UND verteilt wurde.
        require(wait_until(lambda: (COMMAND, after_command) in control.messages),
                'post-withdrawal command delivered to positive control')
        event('observation_started', seconds=OBSERVE)
        # Nur der Hauptthread wartet; die Netzwerkthreads empfangen waehrenddessen
        # weiter Commands, Brokerantworten und moegliche Disconnects.
        time.sleep(OBSERVE)
        require(control.client.is_connected() and not control.closed and
                control.last_ping > command_sent_at, 'control broker connection stayed healthy')
        old_closed = [x for x in old.closed if not x['cleanup']]
        result = classify(post_puback, (COMMAND, after_command) in old.messages,
                          old.client.is_connected(), old.last_ping > command_sent_at,
                          old_closed, old.connects)
        result.update({'old_gateway_connect_count': old.connects,
                       'post_publish_puback': post_puback,
                       'old_gateway_disconnect_events': old_closed,
                       'observation_seconds': OBSERVE,
                       'command_positive_control': 'DELIVERED',
                       'old_subscription_recreated_after_withdrawal': False,
                       'certificate_revocation_tested': False,
                       'note': 'Connection closure is an observation; cause needs broker evidence.'})
    except Exception as exc:
        result = {'overall': 'INCONCLUSIVE: '+str(exc), 'exit': 2}
        event('test_error', error=str(exc))
        traceback.print_exc()
    finally:
        event('measurement_complete', result=result)
        # Das Messergebnis vor dem absichtlichen Schliessen speichern. Sonst
        # koennte der eigene Cleanup-Disconnect als Brokerreaktion erscheinen.
        (WORK/'report.json').write_text(json.dumps(result, indent=2)+'\n')
        (WORK/'summary.txt').write_text('\n'.join(f'{k}: {v}' for k,v in result.items())+'\n')
        for gateway in (old, control):
            if gateway:
                try:
                    gateway.close()
                except Exception as exc:
                    event('client_cleanup_error', error=str(exc))
        (WORK/'probe_exit_code').write_text(str(result['exit'])+'\n')
        (WORK/'finished').touch()


if __name__ == '__main__':
    main()
PYTHON_WORKER

await_flag() {
# Begrenztes Warten plus Containerpruefung: Ein abgestuerzter Helfer darf weder
# endlos haengen noch als erfolgreich blockierter Client interpretiert werden.
  FLAG_NAME=$1
  FLAG_LIMIT=$2
  FLAG_WAITED=0
  while [ ! -f "$RESULTS/$FLAG_NAME" ]; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_ID" 2>/dev/null)" != true ]; then
      docker logs "$CONTAINER_ID" >&2 || true
      die "Test helper stopped before $FLAG_NAME. See setup.log / runner.log."
    fi
    [ "$FLAG_WAITED" -lt "$FLAG_LIMIT" ] || die "Timed out waiting for $FLAG_NAME."
    sleep 1
    FLAG_WAITED=$((FLAG_WAITED + 1))
    if [ $((FLAG_WAITED % 15)) -eq 0 ]; then
      printf 'Waiting for %s (%s seconds)...\n' "$FLAG_NAME" "$FLAG_WAITED"
    fi
  done
}

printf '\n[1/4] Prepare disposable Python/Paho helper (first run may download image).\n'
# Zertifikate nur lesbar einbinden, Ergebnisse schreibbar. Die Broker-IP wird
# im Testcontainer auf den Namen "broker" abgebildet; die TLS-Namenspruefung
# bleibt aktiv. Das Image und Paho werden vor der ersten ACL-Aenderung vorbereitet.
CONTAINER_ID=$(docker run -d --name "enetec-test10-$RUN_ID" \
  --network "$NETWORK" --add-host "broker:$BROKER_IP" \
  --mount "type=bind,source=$ROOT/certs,target=/certs,readonly" \
  --mount "type=bind,source=$RESULTS,target=/work" \
  -e "TEST_RUN_ID=$RUN_ID" python:3.12-alpine \
  sh -c 'python -m pip install --disable-pip-version-check --no-cache-dir --retries 1 --timeout 15 --target /tmp/paho paho-mqtt==2.1.0 > /work/setup.log 2>&1 && PYTHONPATH=/tmp/paho exec python -u /work/probe.py')
await_flag dependencies_ready 180
docker image inspect python:3.12-alpine -f '{{.Id}}' > "$RESULTS/python-image.txt"
docker compose exec -T broker mosquitto -h > "$RESULTS/broker-version.txt" 2>&1 || true

# Baseline: Das alte Gateway darf Telemetrie senden und Test-Commands lesen.
# Gateway 000002 erhaelt ausschliesslich fuer diesen Test die Sender-/Beobachterrolle.
cat > "$LOCK/baseline-acl" <<ACL_BASELINE
user gw-sim-000001
topic write $TELEMETRY
topic read $COMMAND

user gw-sim-000002
topic write $COMMAND
topic read $COMMAND
topic read $TELEMETRY
ACL_BASELINE
# Entzug: Alle Topic-Rechte des alten Gateways sperren. Die zusaetzliche
# Markerfreigabe fuer den Kontrollclient identifiziert die neue ACL-Version.
cat > "$LOCK/withdrawn-acl" <<ACL_WITHDRAWN
user gw-sim-000001
topic deny #

user gw-sim-000002
topic write $COMMAND
topic read $COMMAND
topic read $TELEMETRY
topic write $COMMAND/acl-generation
ACL_WITHDRAWN

printf '\n[2/4] Establish one old-gateway connection; prove publish and command delivery.\n'
CHANGED=1
# In dieselbe Datei schreiben: Ein Austausch per Rename koennte bei einem
# einzelnen Docker-Datei-Bind-Mount dazu fuehren, dass der Container weiter
# die alte Datei sieht. Der CHANGED-Merker wurde bereits vor dem Schreiben gesetzt.
cat "$LOCK/baseline-acl" > "$ACL"
reload_acl
sleep 1
touch "$RESULTS/start_baseline"
await_flag withdraw_request 90

printf '\n[3/4] Withdraw old-gateway permissions while its connection remains untouched.\n'
# Die laufende Altverbindung bleibt waehrend Dateiaenderung und Reload bestehen,
# soweit der Broker sie nicht selbst schliesst. Genau dieses Verhalten messen wir.
cat "$LOCK/withdrawn-acl" > "$ACL"
reload_acl
sleep 1
touch "$RESULTS/withdrawal_done"
await_flag finished 90

printf '\n[4/4] Measured result (before cleanup)\n'
cat "$RESULTS/summary.txt"
PROBE_EXIT=$(cat "$RESULTS/probe_exit_code")
case "$PROBE_EXIT" in 0|1|2) ;; *) die 'Invalid helper result.' ;; esac
printf '\nA connection that stays open is a recorded finding, not proof of forced termination.\n'
printf 'Next: cleanup closes test clients and verifies the original ACL.\n'
# Dieser Exit loest den registrierten EXIT-Trap aus: Auch nach einem fehlgeschlagenen
# oder unklaren Messergebnis wird die urspruengliche ACL wiederhergestellt.
exit "$PROBE_EXIT"
