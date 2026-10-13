# ENETEC MQTT-Simulationsumgebung: Entwicklung, Aufbau, Benutzung

**Stand:** 2026-10-12 · **Bezug:** ENTC-63 (Testrahmen), ENTC-58 (Architektur), ENTC-59 (Broker-Auswahl), ENTC-31 (Zertifikate), ENTC-61 (Nachrichtenspezifikation)

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
5. **Wie hängt das alles zusammen?** → der Baukasten im Browser (`web/baukasten/index.html`).

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
| **7. Weitere Broker** | Konfiguration für EMQX; bis 08.10. auch HiveMQ (mit Lab-Erweiterung) und Bevywise, seit 12.10. gestrichen (Git-Historie). Neu: Pro Mosquitto von Cedalo. | `make acceptance BROKER=emqx` bzw. `BROKER=cedalo` |
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
  dataset/*                                            (Pro Mosquitto nutzt dieselbe acl wie Mosquitto)
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
  Broker unter Test: Mosquitto (Lab-Referenz) │ EMQX │ Pro Mosquitto (Cedalo, Lizenz nötig)
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

Der erste Lauf dauert einige Minuten (Images laden, Zertifikate ausstellen).

**Linux:** läuft genauso. Der Broker-Schlüssel wird dort für die Container-Benutzer lesbar gemacht
(Mosquitto 2 liest ihn als Benutzer 1883, EMQX als 1000; Docker Desktop auf dem Mac regelt das selbst).
Ohne Netz im Build-Container (Firmen-Proxy) läuft Python mit `SIM_LOCAL=1` auf dem Host: dafür
`python3` ab 3.11, `pip install paho-mqtt==2.1.0` und OpenSSL 3, also z. B.
`SIM_LOCAL=1 make acceptance BROKER=emqx`.

**Neu beginnen:** `make clean` löscht Zertifikate, Broker-Daten und Logs. Die Ergebnisse unter
`results/` bleiben erhalten. Nach einem `make init` oder `make clean` werden Zertifikate bei Bedarf
automatisch neu ausgestellt.

## 5. Benutzen

| Befehl | Zweck |
|---|---|
| `make acceptance` | Abnahme gegen den Lab-Mosquitto. Exit 0 nur, wenn alle Pflichtfälle bestehen |
| `make acceptance BROKER=emqx` | Abnahme gegen ein anderes Profil (`make brokers` listet sie: `mosquitto-lab`, `emqx`, `emqx-registry`, `cedalo`) |
| `make acceptance WIRE=lab-eicp` | mit dem früheren Topic-Schema und Client-ID = CN |
| `make simulate` | 24 h Verkehr, zeitgerafft (×720, etwa 2 Minuten), danach Auswertung |
| `make simulate BROKER=emqx SPEED=2880 GATEWAYS=gw-sim-000001,gw-sim-000006` | mit Optionen |
| `make compare A=emqx B=mosquitto-lab` | zwei Broker vergleichen (letzter vollständiger Lauf je Broker) |
| `make compare A=cedalo B=emqx FRESH=1` | Abnahme für beide neu ausführen, dann vergleichen |
| `make decide` | gewichtete Entscheidungsmatrix aus `sim/decision.toml` und den letzten Läufen |
| `make web` | Daten der Baukasten-Webseite aus dem Repo neu erzeugen (Flotte, Referenzläufe) |
| `make fleet` | Flotte, Datensatz, ACLs und Zertifikate neu erzeugen (nach Änderung von `sim/config.toml`); `make fleet WIRE=lab-eicp` für die Einzeltests 04–10 |
| `make sim-test` | Unit-Tests im Container (`SIM_LOCAL=1`: lokal; mit `mosquitto` und `openssl` auf dem PATH auch die End-to-End-Tests gegen einen echten Broker) |
| `make web-check` | Browser-Test beider Webseiten: jede Station, jede Aktion, beide Sprachen, Breiten, CSP, keine externen Anfragen (braucht Node.js und Playwright) |
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

### Die Erklärung

`web/erklaerung/index.html` im Browser öffnen: eine interaktive Erklärung der Strecke. Zwölf
Stationen folgen einer Nachricht vom Gateway über Ausweiskontrolle,
Broker, Rechteliste, Session-Speicher und Audit-Log in die Cloud und als Command zurück. An jeder
Station lässt sich etwas auslösen (verbinden, mit falschem Zertifikat oder fremder Client-ID, Netz
weg, verbotenes PUBLISH/SUBSCRIBE, Command an ein Offline-Gateway, Session läuft ab). Die Seite zeigt
den Ablauf mit MQTT-5-Reason-Codes und schreibt das Audit-Log im Format des Lab-Mosquitto mit.
Gezeigt wird das **Soll** nach R01–R15, nicht ein bestimmter Broker; was die Broker im Lab wirklich
tun, zeigt der Baukasten. Deutsch und Englisch. Aufbau und Stilanalyse: [`ERKLAERUNG.md`](ERKLAERUNG.md).

### Der Baukasten

`web/baukasten/index.html` direkt im Browser öffnen (kein Server, kein Docker nötig). Die Seite ist
zweisprachig: **DE | EN** oben rechts (oder `index.html?lang=en`).

- **Aufbauen:** Installationen, Gateways, Broker und Cloud aus der Bausteinleiste auf die Montageplatte ziehen
  oder antippen.
- **Gateway einstellen:** Zertifikat (gültig, abgelaufen, fremde CA, widerrufen …), Client-ID (erlaubt,
  fremd, CN statt abgeleitet), Anbindung, Seriennummer.
- **Aktionen auslösen:** state senden, fremde Topics, Abos, Offline-Command, Last Will, Widerruf,
  Rechte entziehen, Broker-Neustart, Reconnect-Sturm. Jede Aktion zeigt den Ablauf und das Ergebnis,
  das der gewählte Broker **im Lab tatsächlich** hatte, mit Testfall, Anforderung und Beobachtung aus dem
  Referenzbericht. Ohne Lauf steht dort „nicht gemessen“.
- **Broker tauschen:** Die Leiste über dem Schaltschrank zeigt alle Broker mit ihrer Pflichtquote. Ein Klick
  tauscht den Broker und spielt die letzte Aktion dort noch einmal ab; im Prüfprotokoll gibt es dafür
  „Gleicher Fall bei den anderen Brokern“.
- **Paket-Monitor:** Unter dem Schaltschrank laufen die MQTT-Pakete des Ablaufs mit (simuliert, das
  Ergebnis stammt aus dem Lab-Lauf).
- **Lernpfad:** sieben geführte Schritte mit Fortschritt.
- **Pult:** Brokervergleich je Anforderung, generierte ACLs, Glossar.
- **Export:** Der Aufbau wird zu `sim/config.local.toml`. Damit erzeugt `make fleet` genau diese Gateways,
  mit Seriennummern, Client-IDs und Anbindungen wie im Baukasten. `sim/config.local.toml` ergänzt
  `sim/config.toml` und wird nicht eingecheckt; zurück zur Lab-Flotte mit
  `rm sim/config.local.toml && make fleet`.

Neue Referenzläufe kommen über `web/baukasten/sources.toml` und `make web` auf die Seite.

**Sicherheit der Seite:** Sie lädt nichts von Dritten (Schriften sind eingebettet, SIL OFL 1.1),
schickt nichts weg und führt nur ihr eigenes Skript aus (Content-Security-Policy mit Skript-Hash,
den `make web` schreibt). Der Aufbau wird nur im eigenen Browser gespeichert (`localStorage`) und beim
Laden geprüft; ein manipulierter Stand wird verworfen.

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
[`brokers/cedalo/`](../brokers/cedalo/README.md) (Pro Mosquitto, mit Lizenz und Herstellerangaben samt Quellen).

## 7. Stand der Ergebnisse (2026-10-13)

**Wire-Profil v13 (aktuell), Docker-Lab:**

| Broker | Pflichtfälle | Beratend | Simulation |
|---|---|---|---|
| EMQX 5.8.6 + Registry (Lab-Prototyp, [`brokers/emqx-registry/`](../brokers/emqx-registry/README.md)) | **34 PASS, abgenommen** | wie EMQX | PASS in 2 von 3 Läufen (einmal letzter Schwung zu spät) |
| EMQX 5.8.6 (Kandidat, führend) | **31 PASS**, 3 FAIL (ID-01, ID-03, DUP-01) | RST-01 PASS (Durable Sessions), EXP-01 FAIL, ACL-14 PARTIAL, MTLS-07/-08, REV-01, LEG-01 FAIL | PASS, 10/10 Prüfungen |
| Mosquitto 2.0.18 (Lab-Referenz, Basis von Pro Mosquitto) | 25 PASS, 3 FAIL (ID-01, ID-03, DUP-01), 6 PARTIAL | RST-01 PASS, EXP-01 PASS, ACL-14 PASS, MTLS-08, REV-01, LEG-01 FAIL | PASS, 10/10 Prüfungen |
| Pro Mosquitto (Cedalo, Kandidat) | Profil und Konfiguration vorbereitet, noch kein Lauf (Lizenz nötig) | – | – |

Berichte: [`2026-10-13-emqx-5.8.6-v13.md`](mqtt-tests/reference/2026-10-13-emqx-5.8.6-v13.md),
[`2026-10-13-mosquitto-2.0.18-v13.md`](mqtt-tests/reference/2026-10-13-mosquitto-2.0.18-v13.md). Die
Simulation (10 Gateways, 24 h in 2 Minuten, 57 Netzabbrüche) hat bei beiden Brokern alle 2.500
Zustandsmeldungen und 115 Commands zugestellt, auch die 60 Commands, die während eines Abbruchs
gesendet wurden. EMQX mit Durable Sessions hatte im Lab-Container eine deutlich höhere Latenz
(p50 104 ms, p95 430 ms) als Mosquitto (p50 1 ms); das ist kein Lasttest, zeigt aber die Kosten der
Plattenspeicherung.

**Profil lab-eicp (bis 2026-10-01, historisch):** Mosquitto 23 PASS / 2 FAIL / 6 PARTIAL,
EMQX 29/31 (Client-ID-Bindung, doppelte Client-ID).

**Cedalo laut Herstellerangaben** (recherchiert 12.10., nicht im Lab geprüft; Quellen in
[`brokers/cedalo/README.md`](../brokers/cedalo/README.md)): native Google-Pub/Sub-Bridge, HA-Cluster ab
3 Knoten, Zertifikatsverwaltung mit Widerruf und Trennen von Clients im Management Center, Persistent
Queueing, Audit Trail. Keine Angabe gefunden zu Client-ID-Bindung (R06), Takeover-Schutz (R11) und
Zertifikaten ohne CN (R16), genau den Punkten, an denen Open-Source-Mosquitto scheitert.

**Wichtigste Befunde**
- **Client-ID-Bindung (R06) und doppelte Client-ID (R11)** sind bei beiden Brokern allein die einzigen offenen Pflichtpunkte. Beide lassen eine fremde Client-ID zu und lassen eine zweite Verbindung die Session übernehmen. **Für EMQX gelöst im Lab-Prototyp:** Ein HTTP-Authenticator fragt bei jedem Verbindungsaufbau eine Registry (Zertifikat → Client-ID, Abfrage offener Verbindungen über die REST-API); damit 34 von 34 Pflichtfällen. Im Betrieb muss das die echte, redundante Registry aus ENTC-47 sein. Für Mosquitto bräuchte es ein Plugin.
- **EMQX** besteht Deny-by-default, Richtungstrennung und Cross-Gateway-Sperren vollständig, mit signalisierter Ablehnung (SUBACK 0x87). Angenommene Verbindungen loggt die Open-Source-Ausgabe nur über eine Regel (`audit_client_connected`). EKU wird in 5.8.6 nicht geprüft, Widerruf nur über CRL-Verteilpunkte.
- **Zielkonflikt bei EMQX:** Durable Sessions halten Session und Commands über einen Neustart, liefern dann aber abgelaufene Commands (Message Expiry) noch aus. Ohne sie ist es umgekehrt. Für einen Cluster fehlt dem Open-Source-Image der replizierte Speicher.
- **Mosquitto** meldet verweigerte Subscriptions nicht als Ablehnung (SUBACK 0x01, Zustellung bleibt aus). Mit `persistence true` übersteht die Session einen Neustart; der frühere Befund „Session nach Neustart weg“ war ein Fehler im Fall RST-01 (Session mit Clean Start = true eröffnet), seit 13.10. behoben.
- **Widerruf bei aktiver Verbindung** braucht mehr als eine CRL beim Verbindungsaufbau: Der Broker muss betroffene Sessions trennen. Keiner der beiden Broker erreicht in der Lab-Konfiguration offene oder neue Verbindungen.
- **Legacy-Zertifikate (AWS IoT)** enthalten keine Gateway-ID. Ein Broker braucht eine Registry-Zuordnung (Fingerprint → Gateway-ID), oder die Gateways bekommen neue Zertifikate mit der ID im CN.
- **Doppelte Client-ID** hat einen Zielkonflikt: Nach einem stillen Verbindungsabbruch lehnt der Broker Reconnects ab, bis der Keep-alive abläuft (bis ca. 180 s).

Berichte: `docs/mqtt-tests/reference/`. Legacy-Analyse: [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md).

## 8. Fehlersuche

| Meldung | Ursache und Lösung |
|---|---|
| `No rule to make target 'acceptance'` | alter Ordner oder alte ZIP. Version prüfen (`cat VERSION`, aktuell `2026-10-13-r3` oder neuer), neue ZIP über den Ordner entpacken (`unzip -o`) |
| Baukasten zeigt „Keine Lab-Daten eingebaut“ | `make web` im Lab-Ordner ausführen und die Seite neu laden |
| Baukasten bleibt leer, Konsole meldet „Content Security Policy“ | Skript der Seite wurde geändert, ohne `make web` auszuführen: `make web` schreibt den neuen Skript-Hash |
| `make fleet` erzeugt eine andere Flotte als erwartet | `sim/config.local.toml` aus dem Baukasten liegt noch im Ordner; zurück mit `rm sim/config.local.toml && make fleet` |
| `This original PoC test uses the earlier topic layout` | Einzeltests 04–10 brauchen das alte Schema: `make fleet WIRE=lab-eicp`, danach zurück mit `make fleet` |
| RST-01 / REV-01 / ACL-14 INCONCLUSIVE mit `hook … not available` oder `unsupported` | Broker nicht vom Lab gestartet oder Profil ohne `[hooks]`: `SIM_HOOK_RESTART` / `SIM_HOOK_CRL_RELOAD` / `SIM_HOOK_ACL_RELOAD` setzen. Ändert das Abnahmeergebnis nicht |
| `Different wire profiles` in `make compare` | die beiden Läufe nutzen unterschiedliche Topic-Schemata; beide mit demselben `WIRE` neu laufen lassen (`FRESH=1`) |
| `Negative identities failed` | alte ZIP ohne OpenSSL-3-Fix, oder Docker läuft nicht |
| `failed to get console` / `pull access denied for enetec-sim` | alte ZIP; aktuelle Version baut das Image mit `docker build -q` |
| `certs/... does not chain to the current lab CA` | Zertifikate einer früheren CA; `make fleet` stellt sie neu aus, sonst `make clean` |
| `Broker certificate has no SAN "cedalo"` | Lab aus einer älteren Version; `make clean && make acceptance BROKER=…` |
| `pull access denied` für `registry.cedalo.com` | `docker login registry.cedalo.com` mit den Zugangsdaten aus der Cedalo-Testanmeldung; Lizenzdatei nach `brokers/cedalo/license/license.lic` |
| alle Fälle INCONCLUSIVE | Broker nicht erreichbar (Port, Host, Container läuft?) |
| LOG-Fälle INCONCLUSIVE | kein Broker-Log übergeben oder Log-Muster im Profil passen nicht: `SIM_BROKER_LOG=…` setzen und Muster anpassen |
| `Unable to load server key file "/mosquitto/certs/broker/broker.key"` (Linux) | Lab aus einer älteren Version: Schlüssel war nur für den Host-Benutzer lesbar. `make acceptance` korrigiert das selbst, sonst `chmod 644 certs/broker/broker.key` (Test-Schlüssel) |
| `429 Too Many Requests` beim Laden eines Images | Docker-Hub-Limit für anonyme Abrufe: `docker login` oder das Image über einen Spiegel laden und umbenennen, z. B. `docker pull mirror.gcr.io/emqx/emqx:5.8.6 && docker tag mirror.gcr.io/emqx/emqx:5.8.6 emqx/emqx:5.8.6` |
| `cluster discovery strategy must be 'singleton'` (EMQX startet nicht) | Durable Sessions mit lokalem Speicher gehen nur mit einem Knoten: `cluster.discovery_strategy = singleton` in `brokers/emqx/emqx.conf` |
| Port belegt | anderer Broker oder Container; `docker compose down`. Mosquitto nutzt 8883, EMQX 8884, Pro Mosquitto 8885, EMQX + Registry 8886 |
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
1. Den Registry-Prototyp für EMQX ([`brokers/emqx-registry/`](../brokers/emqx-registry/README.md)) in eine echte, redundante Komponente überführen (Registry aus ENTC-47) und das Verhalten beim stillen Linkverlust (R11 blockiert Reconnects bis zum Keep-alive) mit ENETEC abstimmen.
1. Den EMQX-Zielkonflikt R20 (Message Expiry) gegen R22 (Neustart) entscheiden oder mit einer neueren EMQX-Version erneut messen.
2. Pro Mosquitto: 30-Tage-Test anfordern, `make acceptance BROKER=cedalo`, offene Punkte (R06, R11, R16, Pub/Sub-Bridge, Preis On-Premises) bei Cedalo erfragen ([`brokers/cedalo/README.md`](../brokers/cedalo/README.md)).
3. Gewichte in `sim/decision.toml` mit SOLHEA/ENETEC abstimmen und die Handbewertungen mit Quellen füllen.
4. Lasttest für die 15.000 Verbindungen und Pub/Sub-Anbindung, getrennt von der funktionalen Abnahme.
5. Ableitungs-Algorithmus der Client-ID (ENTC-47) und Paketgrenze (ENTC-61) übernehmen, sobald entschieden.

## 10. Weiterführende Dokumente

| Dokument | Inhalt |
|---|---|
| [`ERKLAERUNG.md`](ERKLAERUNG.md) | Interaktive Erklärung: Erzählweise, Bildsprache, Soll-Modell, Stationen bearbeiten |
| [`STAND-2026-10-12.md`](STAND-2026-10-12.md) | Aktueller Stand: Kandidaten EMQX und Pro Mosquitto (Cedalo), nächste Schritte |
| [`STAND-2026-10-08.md`](STAND-2026-10-08.md) | Stand vom 08.10. (historisch, mit HiveMQ und Bevywise) |
| [`../brokers/cedalo/README.md`](../brokers/cedalo/README.md) | Pro Mosquitto: Einrichtung, Erwartung, Herstellerangaben mit Quellen |
| [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md) | Wire-Profil, Anforderungen R01–R24, PASS-Regeln, Hooks, Vergleich, Entscheidungsmatrix |
| [`../web/baukasten/index.html`](../web/baukasten/index.html) | Baukasten-Webseite |
| [`AI-PLAYBOOK.md`](AI-PLAYBOOK.md) | Regeln und Rezepte für KI-Assistenten in diesem Repo |
| [`mqtt-tests/synthetic-simulation.md`](mqtt-tests/synthetic-simulation.md) | Datenmodell, Annahmen, Simulation, Referenzlauf |
| [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md) | Analyse des AWS-Zertifikats, Rotation, Fragen an ENETEC |
| [`mqtt-tests/reference/`](mqtt-tests/reference/) | Berichte der Referenzläufe und der Vergleich |
| [`../README.md`](../README.md) | das ursprüngliche Lab und die Einzeltests 04–10 |
