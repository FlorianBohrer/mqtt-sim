# ENETEC MQTT-Simulationsumgebung: Entwicklung, Aufbau, Benutzung

**Stand:** 2026-10-08 · **Bezug:** ENTC-63 (Testrahmen), ENTC-58 (Architektur), ENTC-59 (Broker-Auswahl), ENTC-31 (Zertifikate), ENTC-61 (Nachrichtenspezifikation)

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

Die Umgebung beantwortet vier Fragen:

1. **Erfüllt ein Broker die Sicherheitsanforderungen?** (mTLS, Identität, Zugriffsrechte, doppelte
   Client-ID, QoS 1, Sessions, Logs, Last Will, Neustart, Widerruf) → die Abnahme (`make acceptance`).
2. **Verhält er sich unter realistischem Verkehr korrekt?** (24 Stunden Telemetrie, Ausfälle,
   Reconnect-Sturm, Commands an offline Gateways) → die Simulation (`make simulate`).
3. **Wie schneiden zwei Broker im direkten Vergleich ab?** → der Vergleich (`make compare`).
4. **Wie sieht die Entscheidungsgrundlage gewichtet aus?** → die Entscheidungsmatrix (`make decide`).

Sie ersetzt keine Entscheidung. Kosten, Betrieb, Support und Skalierung gehen nur als belegte
Handbewertung in die Matrix ein; offene Punkte bleiben offen (siehe Abschnitt 9).

**Seit 2026-10-08** spricht das Lab standardmäßig das Topic-Schema aus dem MQTT wire contract v1.3:
`enetec/v1/{clientId}/state` (Gerät → Cloud) und `enetec/v1/{clientId}/cmd` (Cloud → Gerät), mit einer
aus der Seriennummer abgeleiteten Client-ID. Das frühere Schema bleibt als `WIRE=lab-eicp` erhalten.

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
| **9. Wire contract v1.3** (08.10.) | Topics `enetec/v1/{clientId}/state\|cmd`, Client-ID als Pseudonym der Seriennummer (ENTC-47; Algorithmus noch offen, im Lab ein Platzhalter), Registry Zertifikat → Seriennummer → Client-ID. Das alte Schema bleibt als Kompatibilitätsprofil. | `make acceptance` (v13), `WIRE=lab-eicp` |
| **10. Offene Fälle aus dem Current State** (08.10.) | Binärtransport, Last Will (auch auf fremde Topics), Message Expiry, Payload-Größen, Broker-Neustart, Widerruf und ACL-Entzug bei aktiver Verbindung. Die drei letzten brauchen eine Aktion am Broker mitten im Lauf (Hooks). Dazu die gewichtete Entscheidungsmatrix. | R18–R24, `make decide` |

**Gelernt auf dem Weg**
- **Negativfälle brauchen eine Positivkontrolle.** Ohne sie wäre „Broker nicht erreichbar“ als „abgelehnt“ gewertet worden. Jetzt zählt ein Timeout nie als PASS, und ohne bestandene Kontrolle wird alles INCONCLUSIVE.
- **PUBACK allein beweist nichts.** Ob ein Zugriff gesperrt ist, wird daran gemessen, ob ein autorisierter Zeuge die Nachricht sieht.
- **macOS hat LibreSSL.** Die Zertifikatsskripte 12 und 15 laufen deshalb im Container mit OpenSSL 3.
- **`docker compose build` braucht ein Terminal.** Das Image wird mit `docker build -q` gebaut.
- **Identitäten müssen über Läufe stabil bleiben.** Wären Negativ- und Legacy-Zertifikate bei jedem Lauf neu erzeugt worden, hätte der Broker (Registry, CRL) nicht mehr gepasst. Sie werden nur bei Bedarf neu ausgestellt.
- **Änderungen am laufenden Broker brauchen Zeit.** Ein Entzug gilt erst als wirksam, wenn er innerhalb des Beobachtungsfensters greift; ein zu kurzes Warten hätte einen Broker, der alle 2 s nachlädt, zu Unrecht durchfallen lassen.

## 3. Aufbau

```text
                      sim/config.toml  (Flotte, Verkehr, Ausfälle, Annahmen)
                              │ make fleet
        ┌─────────────────────┼──────────────────────────────┐
        ▼                     ▼                              ▼
  synthetic/              Zertifikate (certs/)         Broker-Rechte, generiert:
  fleet.json              Lab-CA, je Gateway/Service,  mosquitto/config/acl
  client_identities.tsv   negative, legacy, rotation   brokers/emqx/acl.conf
  dataset/*                                            brokers/hivemq/permissions.tsv, client_ids.tsv
        │                     │
        ▼                     ▼
  sim-Container (Python, paho-mqtt 2.1, OpenSSL 3)
   ├─ acceptance : Pflicht- und Advisory-Fälle      ──►  results/acceptance-<lauf>/
   │     └─ Hooks (Neustart, Widerruf, ACL-Entzug) ◄──  scripts/13_acceptance.sh
   ├─ simulate   : 24 h Verkehr gegen den Broker    ──►  results/simulation-<lauf>/
   ├─ compare    : zwei Broker nebeneinander        ──►  results/compare-<A>-vs-<B>-<zeit>/
   └─ decide     : gewichtete Matrix (decision.toml) ──►  results/decision-<zeit>/
        │ MQTT 5 + mTLS
        ▼
  Broker unter Test: Mosquitto │ HiveMQ CE + Erweiterung │ EMQX │ Bevywise (extern)
```

**Akteure im Test:** Jedes Gateway hat ein eigenes Zertifikat (CN = Gateway-ID des Labs) und eine
erlaubte Client-ID. Im Profil v13 ist das ein Pseudonym der Seriennummer, z. B. `gw-sim-000001` →
`c4b06565c3cea7d66c4a6`; im Profil `lab-eicp` ist es der CN. Die Cloud-Platzhalter
`svc-sim-cloud-ingest` (liest alle `state`) und `svc-sim-cloud-command` (schreibt alle `cmd`) stehen
für die spätere Pub/Sub-Brücke und den Command-Pfad. Peripheriegeräte sind nur Daten, keine
MQTT-Clients.

**Quellenregeln.** Nichts wird erfunden. In `sim/config.toml` ist jede Annahme als SOURCE (Projektunterlage),
INTERPRETED, ASSUMPTION oder OPEN gekennzeichnet. Die Ableitung der Client-ID ist ein Platzhalter
(`lab-sha256-v0`), weil der echte Algorithmus offen ist. Die Simulation sendet `telemetry.report` im
Format von `samples/telemetry.json` als **synthetisches JSON-Fixture**, nicht im v1.3-Binärformat.
Payloads der Abnahme sind opake Bytes.

### Verzeichnisse

| Pfad | Inhalt |
|---|---|
| `sim/config.toml` | Konfiguration der Flotte, des Verkehrs und des Wire-Profils |
| `sim/decision.toml` | Gewichte, Kandidaten und belegte Handbewertungen der Entscheidungsmatrix |
| `sim/enetec_sim/` | Python-Programm (Generator, Simulation, Abnahme, Vergleich, Matrix) |
| `sim/targets/*.toml` | Broker-Profile |
| `sim/tests/` | Unit- und Integrationstests |
| `synthetic/` | erzeugte Flotte und Datensatz (eingecheckt, reproduzierbar) |
| `scripts/` | Zertifikate, Start-Skripte; die Skripte 04–10 sind die ursprünglichen Einzeltests |
| `brokers/<broker>/` | Konfiguration und Anleitung je Broker |
| `docs/mqtt-tests/` | Detaildoku und Referenzberichte |
| `certs/`, `results/`, `data/` | lokal erzeugt, **nicht** eingecheckt |

## 4. Aufsetzen

**Voraussetzungen:** Docker (mit Docker Compose v2) und `make`. Python wird nicht gebraucht, es läuft
im Container. macOS und Linux werden unterstützt.

```bash
mkdir -p ~/Projects/enetec
unzip -q ~/Downloads/enetec_mtls_lab.zip -d ~/Projects/enetec
cd ~/Projects/enetec/enetec_mtls_lab
cat VERSION
```

Das Lab ist ein eigenständiger Ordner ohne Git, GitHub oder andere Abhängigkeiten. Als Ablageort
empfehle ich einen festen Pfad ohne Leerzeichen und ohne iCloud-Sync (z. B. `~/Projects/enetec/`),
weil `certs/` private Lab-Schlüssel enthält.

**Neue Version einspielen:** neue ZIP herunterladen und über den bestehenden Ordner entpacken. Dabei
bleiben `results/`, `certs/` und `data/` erhalten, weil sie nicht in der ZIP sind:

```bash
unzip -o -q ~/Downloads/enetec_mtls_lab.zip -d ~/Projects/enetec
cat ~/Projects/enetec/enetec_mtls_lab/VERSION
```

Die Version steht in der Datei `VERSION` (auch `make version`). Hat der Browser die ZIP unter einem
anderen Namen gespeichert (z. B. `enetec_mtls_lab (1).zip`), den Namen entsprechend einsetzen.


**Hinweis zsh (macOS):** `#` am Zeilenanfang oder hinter einem Befehl ist im Terminal standardmäßig kein Kommentar. Kopiere deshalb nur die Befehle ohne Kommentare, oder führe einmal `setopt interactive_comments` aus.

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
| `make acceptance WIRE=lab-eicp` | mit dem früheren Topic-Schema und Client-ID = CN |
| `make simulate` | 24 h Verkehr, zeitgerafft (×720, etwa 2 Minuten), danach Auswertung |
| `make simulate BROKER=hivemq SPEED=2880 GATEWAYS=gw-sim-000001,gw-sim-000006` | mit Optionen |
| `make compare A=hivemq B=mosquitto-lab` | zwei Broker vergleichen (letzter vollständiger Lauf je Broker) |
| `make compare A=hivemq B=emqx FRESH=1` | Abnahme für beide neu ausführen, dann vergleichen |
| `make decide` | gewichtete Entscheidungsmatrix aus `sim/decision.toml` und den letzten Läufen |
| `make fleet` | Flotte, Datensatz, ACLs und Zertifikate neu erzeugen (nach Änderung von `sim/config.toml`); `make fleet WIRE=lab-eicp` für die Einzeltests 04–10 |
| `make sim-test` | Unit-Tests im Container |
| `make brokers` | verfügbare Profile |
| `make clean` | lokale Zertifikate und Broker-Daten löschen |

**Jeder Lauf endet mit einer Zusammenfassung** (Ergebnis, Wire-Profil, Anforderungen R01–R24 auf einen Blick, nicht
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
| N/A | Fall gilt für das gewählte Wire-Profil nicht (z. B. ID-03 unter `lab-eicp`) |

### Die Fälle

| Gruppe | Fälle | Prüft |
|---|---|---|
| MTLS | 01–08 | gültiges Zertifikat; ohne Zertifikat, fremde CA, selbstsigniert, abgelaufen, noch nicht gültig, falsche EKU, widerrufen |
| ID | 01–03 | fremde Client-ID; Bindung der Rechte ans Zertifikat; CN statt abgeleiteter Client-ID (nur v13) |
| DUP | 01 | doppelte Client-ID: neue Verbindung ablehnen, bestehende behalten |
| ACL | 01–14 | eigenes `state`/`cmd` erlaubt; fremdes Gateway/Installation, falsche Richtung, Wildcard, unbekanntes Gateway verweigert; ACL-14 Entzug bei aktiver Verbindung (beratend, Hook) |
| QOS / SES / REC | 01–02 / 01–02 / 01 | QoS 1 inkl. Neuzustellung, persistente Session, Reconnect ohne Sturm |
| PAY | 01–03 | Binärtransport byteexakt (Pflicht); 128 B / 12 KB; Überschreitung der Paketgrenze (beratend) |
| LWT / EXP | 01–02 / 01 | Last Will bei Linkverlust (beratend); fremdes Will-Topic gesperrt (Pflicht); Message Expiry (beratend) |
| RST / REV | 01 / 01 | Broker-Neustart mit Session; Widerruf bei aktiver Verbindung (beratend, Hooks) |
| LOG | 01–05 | Connect, TLS-Fehler, ACL-Ablehnung, Disconnect im Log; keine Schlüssel im Log |
| LEG / ROT | 01–02 / 01–02 | Legacy-Zertifikat ohne CN; Rotation mit Überlappung und Rückfall |

Vollständige Regeln: [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md).

## 6. Einen eigenen Broker anbinden

1. Profil kopieren: `cp sim/targets/emqx.toml sim/targets/mein-broker.toml`.
2. Eintragen: `name`, `host`, `port`, bei Bedarf `server_ca`, und unter `[log]` die Muster für das
   Broker-Log. Mit `lab_managed = false` startet der Lauf den Broker nicht selbst.
3. Broker aus der Flotte konfigurieren: Lab-CA als Client-CA vertrauen, Client-Zertifikat verpflichtend,
   CN als Identität, nur die erlaubte Client-ID zulassen (`synthetic/client_identities.tsv`), Rechte aus
   `synthetic/fleet.json` (je Gateway nur eigenes `state` schreiben und eigenes `cmd` lesen; die
   Cloud-Platzhalter je eine Richtung; alles andere verweigern).
4. Optional `[effort]` im Profil: Aufwandsklasse je Anforderung
   (NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE / CUSTOM DEVELOPMENT / UNSUPPORTED).
5. Optional für Neustart, Widerruf und ACL-Entzug: `[hooks] crl_reload` / `acl_reload` im Profil
   (Lab-Broker) oder `SIM_HOOK_RESTART`, `SIM_HOOK_CRL_RELOAD`, `SIM_HOOK_ACL_RELOAD` (eigener Broker).
6. `make acceptance BROKER=mein-broker SIM_BROKER_LOG=/pfad/zum/broker.log`
7. Kandidat in `sim/decision.toml` eintragen, damit er in `make decide` erscheint.

Vorhandene Profile und Anleitungen: [`brokers/emqx/`](../brokers/emqx/README.md),
[`brokers/hivemq/`](../brokers/hivemq/README.md), [`brokers/bevywise/`](../brokers/bevywise/README.md).

## 7. Stand der Ergebnisse (2026-10-08)

**Wire-Profil v13 (aktuell):**

| Broker | Pflichtfälle | Beratend | Wo getestet |
|---|---|---|---|
| HiveMQ CE 2026.5 + ENETEC-Erweiterung | **34/34 PASS** | Neustart, Widerruf bei aktiver Verbindung, ACL-Entzug: PASS | lokal (ohne Docker) |
| Mosquitto 2.0.18 (Lab) | 25 PASS, 3 FAIL (ID-01, ID-03, DUP-01), 6 PARTIAL | RST-01 FAIL (Session nach Neustart weg), REV-01 FAIL, ACL-14 PASS | lokal (ohne Docker) |
| EMQX 5.8 | noch nicht im v13-Profil gelaufen | – | – |
| Bevywise | Konfiguration vorbereitet (v13-Regeln), kein Broker verfügbar | – | – |

HiveMQ wird laut Current State 08.10 nicht mehr aktiv verfolgt; das Ergebnis zeigt, was eine
Erweiterung leisten kann, und ist keine Produktabnahme.

**Profil lab-eicp (bis 2026-10-01, historisch):** HiveMQ 31/31, Mosquitto 23 PASS / 2 FAIL / 6 PARTIAL,
EMQX 29/31 (Client-ID-Bindung, doppelte Client-ID), Bevywise ohne Evidenz.

**Wichtigste Befunde**
- **Client-ID-Bindung (v13):** Eine abgeleitete Client-ID verlangt, dass der Broker die Zuordnung Zertifikat → erlaubte Client-ID nachschlägt. Mosquitto kann das nicht (ID-03 FAIL); HiveMQ nur mit der Erweiterung (`client_ids.tsv`).
- **Widerruf bei aktiver Verbindung** braucht mehr als eine CRL beim Verbindungsaufbau: Die HiveMQ-Erweiterung beobachtet die CRL und trennt betroffene Sessions; Mosquitto in der Lab-Konfiguration erreicht weder offene noch neue Verbindungen.
- **Broker-Neustart:** Mosquitto 2.0.18 schrieb die Persistenzdatei, nach dem Neustart war die Session trotzdem weg (lokal, mit dem Docker-Image zu wiederholen).
- **Mosquitto:** Client-ID ≠ Zertifikat wird akzeptiert und verdrängt die echte Session. Doppelte Client-ID führt zur Session-Übernahme. Verweigerte Subscriptions werden bestätigt (nur die Zustellung bleibt aus).
- **EMQX:** Deny-by-default, Richtungstrennung und Cross-Gateway-Sperren bestehen vollständig, auch mit signalisierter Ablehnung (SUBACK 0x87). Wie Mosquitto scheitert es an CN ≠ Client-ID und an der doppelten Client-ID; zusätzlich werden falsche Zertifikatsverwendung (EKU), Widerruf (ohne CRL-Verteilpunkte) und Legacy-Zertifikate ohne CN nicht abgefangen (nur beobachtend).
- **HiveMQ CE** hat keine eigene Autorisierung. Die Anforderungen sind nur mit einer Lab-Erweiterung erfüllt (Identität, Client-ID-Bindung, Duplikat-Ablehnung, Widerruf, Deny-by-default). Für Produktion: Anbindung an die Backend-Registry oder die kommerzielle Enterprise Security Extension.
- **Legacy-Zertifikate (AWS IoT)** enthalten keine Gateway-ID. Ein Broker braucht eine Registry-Zuordnung (Fingerprint → Gateway-ID), oder die Gateways bekommen neue Zertifikate mit der ID im CN.
- **Doppelte Client-ID** hat einen Zielkonflikt: Nach einem stillen Verbindungsabbruch lehnt der Broker Reconnects ab, bis der Keep-alive abläuft (bis ca. 180 s).

Berichte: `docs/mqtt-tests/reference/`. Legacy-Analyse: [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md).

## 8. Fehlersuche

| Meldung | Ursache und Lösung |
|---|---|
| `No rule to make target 'acceptance'` | alter Ordner oder alte ZIP. Version prüfen (`cat VERSION`, aktuell `2026-10-08-r1` oder neuer), neue ZIP über den Ordner entpacken (`unzip -o`) |
| `This original PoC test uses the earlier topic layout` | Einzeltests 04–10 brauchen das alte Schema: `make fleet WIRE=lab-eicp`, danach zurück mit `make fleet` |
| RST-01 / REV-01 / ACL-14 INCONCLUSIVE mit `hook … not available` oder `unsupported` | Broker nicht vom Lab gestartet oder Profil ohne `[hooks]`: `SIM_HOOK_RESTART` / `SIM_HOOK_CRL_RELOAD` / `SIM_HOOK_ACL_RELOAD` setzen. Ändert das Abnahmeergebnis nicht |
| `Different wire profiles` in `make compare` | die beiden Läufe nutzen unterschiedliche Topic-Schemata; beide mit demselben `WIRE` neu laufen lassen (`FRESH=1`) |
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
- HA-Failover (RST-01 prüft nur den Neustart eines Knotens)
- Bootstrap-Phase (Wechsel der Rechte nach dem Claim)
- Applikationskorrelation `command_id` ↔ `origin_command_id` (braucht echte Firmware)
- Anbindung an Google Pub/Sub

**Technische Grenzen:**
- Verbindungsabbruch wird als TCP-Close simuliert.
- Broker-Timer laufen in Echtzeit, auch bei zeitgerafftem Verkehr.
- Negative Beobachtungen gelten für das Beobachtungsfenster (Standard 3 s).
- Log-Prüfungen sind Mustersuchen je Profil.

**Nächste Schritte:**
1. EMQX (führender Kandidat) im v13-Profil laufen lassen; für ACL-14 einen Reload der Datei-ACL über die EMQX-API als `acl_reload` hinterlegen.
2. Bevywise gegen eine echte Instanz, Cedalo/Pro Mosquitto als Benchmark anfragen.
3. Gewichte in `sim/decision.toml` mit SOLHEA/ENETEC abstimmen und die Handbewertungen mit Quellen füllen.
4. Lasttest für die 15.000 Verbindungen und Pub/Sub-Anbindung, getrennt von der funktionalen Abnahme.
5. Ableitungs-Algorithmus der Client-ID (ENTC-47) und Paketgrenze (ENTC-61) übernehmen, sobald entschieden.

## 10. Weiterführende Dokumente

| Dokument | Inhalt |
|---|---|
| [`STAND-2026-10-08.md`](STAND-2026-10-08.md) | Zusammenfassung des aktuellen Stands (Ergebnisse, Befunde, offene Punkte) |
| [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md) | Wire-Profil, Anforderungen R01–R24, PASS-Regeln, Hooks, Vergleich, Entscheidungsmatrix |
| [`mqtt-tests/synthetic-simulation.md`](mqtt-tests/synthetic-simulation.md) | Datenmodell, Annahmen, Simulation, Referenzlauf |
| [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md) | Analyse des AWS-Zertifikats, Rotation, Fragen an ENETEC |
| [`mqtt-tests/reference/`](mqtt-tests/reference/) | Berichte der Referenzläufe und der Vergleich |
| [`../README.md`](../README.md) | das ursprüngliche Lab und die Einzeltests 04–10 |
