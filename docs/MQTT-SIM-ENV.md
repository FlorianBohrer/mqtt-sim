# ENETEC MQTT-Simulationsumgebung: Entwicklung, Aufbau, Benutzung

**Stand:** 2026-10-01 · **Bezug:** ENTC-63 (Testrahmen), ENTC-58 (Architektur), ENTC-59 (Broker-Auswahl), ENTC-31 (Zertifikate), ENTC-61 (Nachrichtenspezifikation)

*English version: [MQTT-SIM-ENV.en.md](MQTT-SIM-ENV.en.md)*

Diese Datei erklärt, wie die Simulationsumgebung entstanden ist, wie sie funktioniert, wie man sie
aufsetzt und wie man sie benutzt. Detailtiefe zu einzelnen Themen steht in den verlinkten Dokumenten
unter `docs/mqtt-tests/` und `brokers/`.

---

## 1. Worum es geht

ENETEC wechselt von AWS IoT Core zu Google Cloud. Das MQTT-Backbone zwischen Gateways und Cloud
braucht dafür einen neuen Broker. Bevor einer ausgewählt wird, soll die Kommunikationsschicht
**Gateway ↔ MQTT-Broker** mit simulierten Gateways geprüft werden, und zwar mit Ergebnissen, die
jeder nachvollziehen und wiederholen kann.

Die Umgebung beantwortet drei Fragen:

1. **Erfüllt ein Broker die Sicherheitsanforderungen?** (mTLS, Identität, Zugriffsrechte, doppelte
   Client-ID, QoS 1, Sessions, Logs) → die Abnahme (`make acceptance`).
2. **Verhält er sich unter realistischem Verkehr korrekt?** (24 Stunden Telemetrie, Ausfälle,
   Reconnect-Sturm, Commands an offline Gateways) → die Simulation (`make simulate`).
3. **Wie schneiden zwei Broker im direkten Vergleich ab?** → der Vergleich (`make compare`).

Sie ersetzt keine Entscheidung. Kosten, Betrieb, Support und Skalierung sind nicht Teil der
Abnahme (siehe Abschnitt 9).

## 2. Wie sie entstanden ist

| Phase | Was passiert ist | Ergebnis |
|---|---|---|
| **1. Ausgangspunkt** | Ein manuelles Docker-Lab mit Mosquitto, Test-CA und zwei Gateways. Einzelne Skripte (04–10) zeigten Publish, Cross-Gateway-Zugriff, Client-ID-Lücke, Gateway-Austausch und ACL-Entzug bei aktiver Verbindung. | Gute Experimente, aber keine wiederholbare Abnahme |
| **2. Synthetische Flotte** | Aus den Projektunterlagen wurde eine Flotte abgeleitet: 6 Plants, 10 Gateways, 108 Geräte, 24 h Verkehr auf ~251 Nachrichten pro Gateway und Tag kalibriert (aus 2,51 Mio./Tag bei ~10.000 Gateways). Dazu Ausfälle, ein Reconnect-Sturm, Pufferüberlauf, Commands während Ausfällen. | Reproduzierbare Daten (`sim/config.toml` → `synthetic/`), erzeugt die ACL und alle Zertifikate |
| **3. Simulation** | Jedes Gateway verbindet sich mit eigenem Zertifikat, sendet QoS 1, verliert das Netz (TCP-Abbruch), puffert und verbindet sich mit Clean Start = false neu. Zwei Cloud-Platzhalter lesen d2c und senden c2d. Eine Auswertung vergleicht Plan und Beobachtung. | `make simulate`: 2.500/2.500 Nachrichten, 57/57 Sessions wieder aufgenommen |
| **4. Acceptance-Harness (ENTC-63)** | 31 Pflichtfälle zu 15 Anforderungen (R01–R15), PASS/FAIL je Anforderung, Exit 0 nur wenn alles besteht. Gemessen wird die tatsächliche Zustellung, nicht nur der Return-Code. | `make acceptance` mit Berichten und Evidenz |
| **5. Broker-Profile** | Der Broker ist austauschbar: Ein Profil (`sim/targets/*.toml`) beschreibt Adresse, Zertifikats-Trust und Log-Muster. Die Tests bleiben gleich. | `make acceptance BROKER=<profil>` |
| **6. Legacy und Rotation** | Das echte AWS-IoT-Zertifikat des Test-Gateways `0000000000000005` hatte keinen CN (nur `C=UK, ST=United`, RSA 2048). Daraus entstanden die Fälle LEG und ROT. | R16/R17 (zunächst nur beobachtend) |
| **7. Weitere Broker** | Konfigurationen für Bevywise, EMQX und HiveMQ. HiveMQ CE hat keine eigene Autorisierung, deshalb gibt es eine kleine Lab-Erweiterung. | HiveMQ besteht 31/31, auch im Docker-Lauf |
| **8. Vergleich** | Zwei Profile auswählen, Ergebnisse nebeneinander, Aufwandsklassen je Anforderung. | `make compare A=… B=…` |

**Gelernt auf dem Weg**
- **Negativfälle brauchen eine Positivkontrolle.** Ohne sie wäre „Broker nicht erreichbar“ als „abgelehnt“ gewertet worden. Jetzt zählt ein Timeout nie als PASS, und ohne bestandene Kontrolle wird alles INCONCLUSIVE.
- **PUBACK allein beweist nichts.** Ob ein Zugriff gesperrt ist, wird daran gemessen, ob ein autorisierter Zeuge die Nachricht sieht.
- **macOS hat LibreSSL.** Die Zertifikatsskripte 12 und 15 laufen deshalb im Container mit OpenSSL 3.
- **`docker compose build` braucht ein Terminal.** Das Image wird mit `docker build -q` gebaut.
- **Identitäten müssen über Läufe stabil bleiben.** Wären Negativ- und Legacy-Zertifikate bei jedem Lauf neu erzeugt worden, hätte der Broker (Registry, CRL) nicht mehr gepasst. Sie werden nur bei Bedarf neu ausgestellt.

## 3. Aufbau

```text
                      sim/config.toml  (Flotte, Verkehr, Ausfälle, Annahmen)
                              │ make fleet
        ┌─────────────────────┼──────────────────────────────┐
        ▼                     ▼                              ▼
  synthetic/            Zertifikate (certs/)         Broker-Rechte, generiert:
  fleet.json            Lab-CA, je Gateway/Service,  mosquitto/config/acl
  dataset/*             negative, legacy, rotation   brokers/emqx/acl.conf
                                                     brokers/hivemq/permissions.tsv
        │                     │
        ▼                     ▼
  sim-Container (Python, paho-mqtt 2.1, OpenSSL 3)
   ├─ acceptance : 31 Pflichtfälle + Advisory-Fälle  ──►  results/acceptance-<lauf>/
   ├─ simulate   : 24 h Verkehr gegen den Broker     ──►  results/simulation-<lauf>/
   └─ compare    : zwei Broker nebeneinander         ──►  results/compare-<A>-vs-<B>-<zeit>/
        │ MQTT 5 + mTLS
        ▼
  Broker unter Test: Mosquitto │ HiveMQ CE + Erweiterung │ EMQX │ Bevywise (extern)
```

**Akteure im Test:** Jedes Gateway hat ein eigenes Zertifikat (Client-ID = Gateway-ID = CN). Die
Cloud-Platzhalter `svc-sim-cloud-ingest` (liest alle d2c) und `svc-sim-cloud-command` (schreibt alle
c2d) stehen für die spätere Pub/Sub-Brücke und den Command-Pfad. Peripheriegeräte sind nur Daten,
keine MQTT-Clients (wie in EICP).

**Quellenregeln.** Nichts wird erfunden. In `sim/config.toml` ist jede Annahme als SOURCE (Projektunterlage),
INTERPRETED, ASSUMPTION oder OPEN gekennzeichnet. Die einzige Nachricht ist `telemetry.report` im
Format von `samples/telemetry.json`; Commands laufen im neutralen Namespace `c2d/simulation/…`. Payloads
der Abnahme sind opake Zufallsbytes.

### Verzeichnisse

| Pfad | Inhalt |
|---|---|
| `sim/config.toml` | Konfiguration der Flotte und des Verkehrs |
| `sim/enetec_sim/` | Python-Programm (Generator, Simulation, Abnahme, Vergleich) |
| `sim/targets/*.toml` | Broker-Profile |
| `sim/tests/` | 30 Unit- und Integrationstests |
| `synthetic/` | erzeugte Flotte und Datensatz (eingecheckt, reproduzierbar) |
| `scripts/` | Zertifikate, Start-Skripte; die Skripte 04–10 sind die ursprünglichen Einzeltests |
| `brokers/<broker>/` | Konfiguration und Anleitung je Broker |
| `docs/mqtt-tests/` | Detaildoku und Referenzberichte |
| `certs/`, `results/`, `data/` | lokal erzeugt, **nicht** eingecheckt |

## 4. Aufsetzen

**Voraussetzungen:** Docker (mit Docker Compose v2) und `make`. Python wird nicht gebraucht, es läuft
im Container. macOS und Linux werden unterstützt.

```bash
# Variante A (empfohlen): direkt aus dem Repository
git clone -b claude/relaxed-einstein-96kmav https://github.com/FlorianBohrer/Todo_API.git
cd Todo_API/enetec_mtls_lab

# Variante B: aus der ZIP, dann Version prüfen (muss zum erwarteten Commit passen)
unzip -z enetec_mtls_lab.zip | tail -1
unzip enetec_mtls_lab.zip && cd enetec_mtls_lab
```

Mehr ist nicht nötig. `make acceptance` baut beim ersten Lauf alles selbst:

1. Image `enetec-sim:local` (Python 3.12, paho-mqtt, OpenSSL 3)
2. Test-CA, Broker-Zertifikat, Zertifikate für alle Gateways und Services
3. Negativ-, Legacy- und Rotations-Identitäten
4. den Broker (je nach Profil mit Image-Build)

Der erste Lauf dauert einige Minuten, bei HiveMQ wegen des Maven-Builds länger.

**Neu beginnen:** `make clean` löscht Zertifikate, Broker-Daten und Logs. Die Ergebnisse unter
`results/` bleiben erhalten. Nach einem `make init` oder `make clean` werden Zertifikate bei Bedarf
automatisch neu ausgestellt.

## 5. Benutzen

| Befehl | Zweck |
|---|---|
| `make acceptance` | Abnahme gegen den Lab-Mosquitto. Exit 0 nur, wenn alle Pflichtfälle bestehen |
| `make acceptance BROKER=hivemq` | Abnahme gegen ein anderes Profil (`make brokers` listet sie) |
| `make simulate` | 24 h Verkehr, zeitgerafft (×720, etwa 2 Minuten), danach Auswertung |
| `make simulate BROKER=hivemq SPEED=2880 GATEWAYS=gw-sim-000001,gw-sim-000006` | mit Optionen |
| `make compare A=hivemq B=mosquitto-lab` | zwei Broker vergleichen (letzter vollständiger Lauf je Broker) |
| `make compare A=hivemq B=emqx FRESH=1` | Abnahme für beide neu ausführen, dann vergleichen |
| `make fleet` | Flotte, Datensatz, ACLs und Zertifikate neu erzeugen (nach Änderung von `sim/config.toml`) |
| `make sim-test` | Unit-Tests im Container |
| `make brokers` | verfügbare Profile |
| `make clean` | lokale Zertifikate und Broker-Daten löschen |

**Jeder Lauf endet mit einer Zusammenfassung** (Ergebnis, Anforderungen R01–R17 auf einen Blick, nicht
bestandene Fälle, Broker-Einschränkungen, Pfad zur Evidenz). Danach folgt bei einem nicht bestandenen
Lauf noch die Zeile `make: *** Error 1`; das ist nur make und bedeutet Exit-Code 1.

### Ergebnisse lesen

Ergebnisordner `results/acceptance-<zeit>/`: `report.md` (Tabelle), `report.json`, `summary.txt`,
`events.jsonl` (jede Beobachtung), `broker.log`.

| Wert | Bedeutung |
|---|---|
| PASS | gefordertes Verhalten beobachtet |
| FAIL | gegenteiliges Verhalten beobachtet |
| PARTIAL | Zugriff faktisch gesperrt, die Ablehnung wird aber nicht gemeldet |
| INCONCLUSIVE | keine Evidenz (Broker nicht erreichbar, Setup-Fehler, Log fehlt) |
| advisory | informativer Fall zu einer offenen Entscheidung; zählt nicht für die Abnahme |

### Die Fälle

| Gruppe | Fälle | Prüft |
|---|---|---|
| MTLS | 01–08 | gültiges Zertifikat; ohne Zertifikat, fremde CA, selbstsigniert, abgelaufen, noch nicht gültig, falsche EKU, widerrufen |
| ID | 01–02 | Zertifikat ≠ Client-ID; Bindung der Rechte ans Zertifikat |
| DUP | 01 | doppelte Client-ID: neue Verbindung ablehnen, bestehende behalten |
| ACL | 01–13 | eigenes d2c/c2d erlaubt; fremdes Gateway/Plant, falsche Richtung, Wildcard, unbekanntes Gateway verweigert |
| QOS / SES / REC | 01–02 / 01–02 / 01 | QoS 1 inkl. Neuzustellung, persistente Session, Reconnect ohne Sturm |
| LOG | 01–05 | Connect, TLS-Fehler, ACL-Ablehnung, Disconnect im Log; keine Schlüssel im Log |
| LEG / ROT | 01–02 / 01–02 | Legacy-Zertifikat ohne CN; Rotation mit Überlappung und Rückfall |

Vollständige Regeln: [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md).

## 6. Einen eigenen Broker anbinden

1. Profil kopieren: `cp sim/targets/emqx.toml sim/targets/mein-broker.toml`.
2. Eintragen: `name`, `host`, `port`, bei Bedarf `server_ca`, und unter `[log]` die Muster für das
   Broker-Log. Mit `lab_managed = false` startet der Lauf den Broker nicht selbst.
3. Broker aus der Flotte konfigurieren: Lab-CA als Client-CA vertrauen, Client-Zertifikat verpflichtend,
   CN als Identität, Rechte aus `synthetic/fleet.json` (je Gateway nur eigenes `d2c` schreiben und
   eigenes `c2d` lesen; die Cloud-Platzhalter je eine Richtung; alles andere verweigern).
4. Optional `[effort]` im Profil: Aufwandsklasse je Anforderung
   (NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE / CUSTOM DEVELOPMENT / UNSUPPORTED).
5. `make acceptance BROKER=mein-broker SIM_BROKER_LOG=/pfad/zum/broker.log`

Vorhandene Profile und Anleitungen: [`brokers/emqx/`](../brokers/emqx/README.md),
[`brokers/hivemq/`](../brokers/hivemq/README.md), [`brokers/bevywise/`](../brokers/bevywise/README.md).

## 7. Stand der Ergebnisse (2026-10-01)

| Broker | Pflichtfälle | Wo getestet |
|---|---|---|
| HiveMQ CE 2026.5 + ENETEC-Erweiterung | **31/31 PASS, abgenommen** | lokal und im Docker-Lab auf macOS |
| Mosquitto 2.0.18 (Lab) | 23 PASS, 2 FAIL, 6 PARTIAL | lokal (Docker-Lauf offen) |
| EMQX 5.8 | noch nicht gelaufen | – |
| Bevywise | Konfiguration vorbereitet, noch nicht gelaufen | – |

**Wichtigste Befunde**
- **Mosquitto:** Client-ID ≠ Zertifikat wird akzeptiert und verdrängt die echte Session. Doppelte Client-ID führt zur Session-Übernahme. Verweigerte Subscriptions werden bestätigt (nur die Zustellung bleibt aus).
- **HiveMQ CE** hat keine eigene Autorisierung. Die Anforderungen sind nur mit einer Lab-Erweiterung erfüllt (Identität, Client-ID-Bindung, Duplikat-Ablehnung, Widerruf, Deny-by-default). Für Produktion: Anbindung an die Backend-Registry oder die kommerzielle Enterprise Security Extension.
- **Legacy-Zertifikate (AWS IoT)** enthalten keine Gateway-ID. Ein Broker braucht eine Registry-Zuordnung (Fingerprint → Gateway-ID), oder die Gateways bekommen neue Zertifikate mit der ID im CN.
- **Doppelte Client-ID** hat einen Zielkonflikt: Nach einem stillen Verbindungsabbruch lehnt der Broker Reconnects ab, bis der Keep-alive abläuft (bis ca. 180 s).

Berichte: `docs/mqtt-tests/reference/`. Legacy-Analyse: [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md).

## 8. Fehlersuche

| Meldung | Ursache und Lösung |
|---|---|
| `No rule to make target 'acceptance'` | alter Ordner oder alte ZIP. Version prüfen (`git log --oneline -1` bzw. `unzip -z`), in einem frischen Ordner neu beginnen |
| `Negative identities failed` | alte ZIP ohne OpenSSL-3-Fix, oder Docker läuft nicht |
| `failed to get console` / `pull access denied for enetec-sim` | alte ZIP; aktuelle Version baut das Image mit `docker build -q` |
| `certs/... does not chain to the current lab CA` | Zertifikate einer früheren CA; `make fleet` stellt sie neu aus, sonst `make clean` |
| `Broker certificate has no SAN "hivemq"` | Lab aus einer älteren Version; `make clean && make acceptance BROKER=…` |
| alle Fälle INCONCLUSIVE | Broker nicht erreichbar (Port, Host, Container läuft?) |
| LOG-Fälle INCONCLUSIVE | kein Broker-Log übergeben oder Log-Muster im Profil passen nicht: `SIM_BROKER_LOG=…` setzen und Muster anpassen |
| Port belegt | anderer Broker oder Container; `docker compose down`. Mosquitto nutzt 8883, EMQX 8884, HiveMQ 8885 |
| Zwei Läufe stören sich | Läufe nicht parallel starten; sie verwenden dieselben Client-IDs |

## 9. Grenzen und nächste Schritte

**Nicht abgedeckt:**
- Last mit ~15.000 Gateways
- Broker-Neustart und HA-Failover
- Widerruf bei bestehender Verbindung (nur Tests 09/10 als Einzelskripte)
- Bootstrap-Phase (Wechsel der Rechte nach dem Claim)
- LWT
- Nutzlasten bis 12 KB und Oversize
- Anbindung an Google Pub/Sub

**Technische Grenzen:**
- Verbindungsabbruch wird als TCP-Close simuliert.
- Broker-Timer laufen in Echtzeit, auch bei zeitgerafftem Verkehr.
- Negative Beobachtungen gelten für das Beobachtungsfenster (Standard 3 s).
- Log-Prüfungen sind Mustersuchen je Profil.

**Nächste Schritte:**
1. EMQX und Bevywise im Docker-Lab laufen lassen und alle Broker vergleichen.
2. Gewichtete Entscheidungsmatrix (Kosten, Betrieb, Support, Skalierung) zusätzlich zur Abnahme.
3. Lasttest für die 15.000 Verbindungen.
4. Offene Pflichtfälle ergänzen (Neustart, Failover, Widerruf bei aktiver Verbindung, Bootstrap).
5. Ergebnisse als Jira-Kommentar für ENTC-63/ENTC-59 aufbereiten.

## 10. Weiterführende Dokumente

| Dokument | Inhalt |
|---|---|
| [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md) | Anforderungen R01–R17, PASS-Regeln, Broker-Vergleich |
| [`mqtt-tests/synthetic-simulation.md`](mqtt-tests/synthetic-simulation.md) | Datenmodell, Annahmen, Simulation, Referenzlauf |
| [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md) | Analyse des AWS-Zertifikats, Rotation, Fragen an ENETEC |
| [`mqtt-tests/reference/`](mqtt-tests/reference/) | Berichte der Referenzläufe und der Vergleich |
| [`../README.md`](../README.md) | das ursprüngliche Lab und die Einzeltests 04–10 |
