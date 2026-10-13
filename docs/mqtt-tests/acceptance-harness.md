# ENTC-63 – MQTT Security & Broker Acceptance Harness

**Stand:** 2026-10-08 · **Bezug:** ENTC-63, Eingabe für ENTC-58, ENTC-59 und ENTC-31 · **Semantik-Quelle:** ENTC-61 / MQTT wire contract v1.3 (06.10.2026)

Der Harness macht aus dem Docker/Mosquitto-PoC eine wiederholbare, broker-agnostische
Abnahmesuite für die Kommunikation **Gateway ↔ MQTT-Broker**. Er prüft Transport- und
Sicherheitsverhalten mit simulierten Gateways und liefert deterministische PASS/FAIL-Evidenz
je Anforderung. Die Payloads sind opake Bytes: Es wird keine ENETEC-Command-Semantik
implementiert und keine Applikations-Payload dekodiert.

---

## 0. Wire-Profil (seit 2026-10-08)

Der Harness spricht standardmäßig das Topic-Schema aus **MQTT wire contract v1.3**:

| Profil | Topics | Client-ID | Einsatz |
|---|---|---|---|
| `v13` (Standard) | `enetec/v1/{clientId}/state` (Gerät → Cloud), `enetec/v1/{clientId}/cmd` (Cloud → Gerät) | abgeleitetes Pseudonym der Gateway-Seriennummer (ENTC-47) | aktuelle Abnahme |
| `lab-eicp` | `eicp/v1/sim/{plantId}/gateways/{gatewayId}/d2c\|c2d/...` | Client-ID = Zertifikats-CN (**LEGACY LAB ASSUMPTION**) | Kompatibilitätsläufe, Vergleich mit Berichten bis 2026-10-01, PoC-Tests 04–10 |

```bash
make acceptance                 # v13
make acceptance WIRE=lab-eicp   # früheres Schema
```

- **Ableitung der Client-ID:** `c` + 20 Hex-Zeichen aus SHA-256 über die Seriennummer
  (`lab-sha256-v0`). Das ist ein **Platzhalter des Labs**: Algorithmus, Versionierung und
  Kollisionsbehandlung sind OFFEN (ENTC-47). Der Harness braucht nur die Zuordnung, nicht den
  Algorithmus.
- **Registry:** `synthetic/client_identities.tsv` ordnet Zertifikatsidentität → Seriennummer →
  erlaubte Client-ID zu (Gegenstück zu `mqttClientIdentities/{clientId}`). Ein Broker muss diese
  Zuordnung prüfen können, sonst schlagen ID-01/ID-03 fehl.
- **Isolation:** v1.3 hat keine Plant-Ebene im Topic; Isolation gilt je Client-ID. Der Fall
  ACL-04 prüft deshalb unter v13 ein nicht freigegebenes Topic im eigenen Namensraum statt
  Plant-Spoofing.
- **Payloads:** Die Fälle senden opake Bytes. PAY-01 nutzt die Rahmenform aus v1.3
  (1 Byte, 4 Byte big-endian, Body) mit beliebigen Werten, um Binärtransport zu prüfen. Die
  JSON-Nachrichten der Architektur-Simulation sind ein synthetisches Fixture, nicht das
  v1.3-Binärformat.
- Berichte enthalten das Wire-Profil; `make compare` und `make decide` bevorzugen Läufe des
  aktuellen Profils und weisen auf gemischte Profile hin.

## 1. Verifikationsbefehl

```bash
make acceptance
```

- **Exit 0 nur dann, wenn jeder Pflichtfall PASS ist.** Andernfalls Exit 1, also auch bei
  FAIL, PARTIAL, INCONCLUSIVE oder einem unvollständigen/gefilterten Lauf.
- **Aus sauberem Stand reproduzierbar:** `make clean && make acceptance`. Das Skript erzeugt
  die fehlenden Voraussetzungen selbst:
  1. Lab-CA und Broker-Zertifikat (`01`)
  2. synthetische Flotte mit individuellen Gateway- und Service-Zertifikaten sowie generierter ACL (`11`)
  3. Negativ-Identitäten (`12`), neu erzeugt bei neuer CA oder nach einem Lauf mit REV-01
  4. Start des Compose-Brokers und Ausführung aller Fälle
  5. Übernahme des Broker-Logs der Laufzeit und Erstellung des Berichts
- **Evidenz** liegt unter `results/acceptance-<run>/`:

  | Datei | Inhalt |
  |---|---|
  | `report.md` | Tabelle für Jira/ENTC-59 |
  | `report.json` | maschinenlesbar |
  | `results.json` | Ergebnis je Fall |
  | `events.jsonl` | jede Beobachtung mit Zeitstempel |
  | `broker.log` | Broker-Log des Laufs |

Varianten:

```bash
# ohne Docker für Python (python3 >= 3.11, pip install -r sim/requirements.txt), Broker läuft bereits
SIM_LOCAL=1 SIM_BROKER_LOG=/pfad/zum/mosquitto.log make acceptance

# anderer Broker-Kandidat (ENTC-59)
SIM_TARGET=sim/targets/<broker>.toml SIM_BROKER_HOST=<host> SIM_BROKER_PORT=<port> \
SIM_BROKER_LOG=<exportiertes-broker-log> BROKER_LABEL="<Broker Version>" make acceptance

# einzelne Gruppen zur Fehlersuche (nie als Abnahme gewertet)
SIM_LOCAL=1 PYTHONPATH=sim python3 -m enetec_sim acceptance --only ACL,SES
```

Nicht parallel zu `make simulate` oder den Tests 09/10 ausführen, weil der Harness die echten
Client-IDs der Flotte verwendet.

## 2. Aufbau

| Rolle | Identität | Zweck |
|---|---|---|
| Gateway A | `gw-sim-000001` (Plant `plt_sim_001`, Client-ID `c4b06565…`) | Akteur; Negativ-Zertifikate tragen seine ID |
| Gateway B, C | `gw-sim-000002`, `gw-sim-000003` (beide `plt_sim_002`) | Ziel für fremde Installation (A→B) und fremdes Gateway derselben Installation (C→B) |
| Cloud-Ingest | `svc-sim-cloud-ingest` (liest alle `state`) | Zeuge für Zustellung Gerät → Cloud |
| Cloud-Command | `svc-sim-cloud-command` (schreibt alle `cmd`) | autorisierter Sender Cloud → Gerät |
| Negativ | `certs/negative/*` | ohne Zertifikat, fremde CA (gleicher Name), selbstsigniert, abgelaufen, noch nicht gültig, falsche EKU, widerrufen, unbekannte Gateway-ID, `revoke-live` (wird erst während REV-01 widerrufen) |
| Reconnect | die ersten 10 Gateways der Flotte | gleichzeitiger Linkverlust |

Alle Schlüssel und Zertifikate sind test-only und werden lokal erzeugt. `certs/` ist per
`.gitignore` ausgeschlossen; es werden keine Produktionszertifikate, Cloud-Credentials oder
Geräte-Secrets eingecheckt.

**Messprinzip:** Eine Freigabe oder Sperre wird nicht nur am Return-Code (PUBACK/SUBACK)
erkannt, sondern an der **tatsächlichen Zustellung**. Ein autorisierter Zeuge beobachtet,
ob eine opake Nachricht ankommt. Jeder Fall nutzt eigene Zufalls-Payloads; unter `lab-eicp`
zusätzlich eigene Topics `…/{d2c|c2d}/simulation/<run>/<case>`, unter v13 die exakten
`state`/`cmd`-Topics.

## 3. Anforderungen und Fälle

| Req. | Anforderung (ENTC-63) | Fälle | PASS-Regel |
|---|---|---|---|
| R01 | mTLS mit individuellem X.509-Zertifikat je Gateway | MTLS-01 | A, B, C verbinden mit eigenem Zertifikat und ihrer erlaubten Client-ID, CONNACK 0, 3 verschiedene Zertifikate. **Positivkontrolle:** ohne sie wird jedes andere PASS zu INCONCLUSIVE |
| R02 | ohne Client-Zertifikat abgelehnt | MTLS-02 | TLS-Alert, CONNACK ≥ 128 oder Abbruch vor CONNACK. „Nicht erreichbar“ zählt nie als Ablehnung |
| R03 | nicht vertrauenswürdige CA abgelehnt | MTLS-03 (fremde CA mit identischem CA-Namen), MTLS-04 (selbstsigniert) | wie R02 |
| R04 | ungültige Zertifikate abgelehnt | MTLS-05 (abgelaufen), MTLS-06 (noch nicht gültig); *advisory:* MTLS-07 (EKU, Profil offen – ENTC-31), MTLS-08 (Widerruf, Strategie offen – ENTC-58/31) | wie R02 |
| R05 | Zertifikatsidentität an Gateway-ID gebunden | ID-02 | Mit A's Zertifikat und B's Client-ID bleibt B's Namespace gesperrt (oder die Verbindung wird abgelehnt) |
| R06 | Nur die für die Zertifikatsidentität erlaubte Client-ID wird angenommen | ID-01 (Zertifikat A + Client-ID B), ID-03 (nur v13: Zertifikat A + sein CN statt der abgeleiteten Client-ID) | Verbindung abgelehnt. Andernfalls FAIL mit Nachweis, ob die legitime Session von B verdrängt wurde. Unter `lab-eicp` ist ID-03 N/A |
| R07 | Deny-by-default | ACL-06 (Topic außerhalb jedes Namespace), ACL-13 (gültige Kette, unbekannte Gateway-ID) | PUBACK/SUBACK ≥ 128 (oder Trennung) und keine Zustellung |
| R08 | Publish nur in eigenes `state` (lab-eicp: d2c) | ACL-01 (eigenes `state`, Positivkontrolle), ACL-05 (eigenes `cmd` = falsche Richtung) | ACL-01: PUBACK < 128 und zugestellt; ACL-05: abgelehnt und nicht zugestellt |
| R09 | Subscribe nur auf eigenes `cmd` (lab-eicp: c2d) | ACL-07 (eigenes `cmd`, Positivkontrolle), ACL-10 (eigenes `state` = falsche Richtung) | ACL-07: SUBACK < 128 und Command zugestellt; ACL-10: nichts zugestellt und SUBACK ≥ 128 |
| R10 | Topics anderer Gateways und Installationen gesperrt (auch Last Will) | ACL-02/-03 (Publish in fremdes `state`, andere/gleiche Installation), ACL-04 (v13: nicht freigegebenes Topic im eigenen Namensraum; lab-eicp: eigene ID unter fremdem Plant), ACL-08/-09 (Subscribe fremdes `cmd`), ACL-11 (fremdes `state` mitlesen), ACL-12 (Wildcard `enetec/v1/#`), LWT-02 (Last Will auf fremdes `state`) | keine Zustellung **und** Ablehnung signalisiert; LWT-02: Will wird nicht veröffentlicht (Ablehnung beim CONNECT oder stilles Verwerfen) |
| R11 | Doppelte Client-ID übernimmt nicht still die aktive Session | DUP-01 | zweite Verbindung abgelehnt **und** die bestehende publiziert danach weiter |
| R12 | QoS 1 | QOS-01 (PUBACK + Zustellung mit QoS 1), QOS-02 (Link bricht nach PUBLISH und vor PUBACK ab, Reconnect mit Clean Start = false) | QOS-02: Session vorhanden, PUBACK nach Reconnect, mindestens eine Zustellung (Duplikate zulässig und gezählt) |
| R13 | Clean Start = false / persistente Session | SES-01; *advisory:* SES-02 (Clean Start = true verwirft die Session) | Command, das während des Offline-Zustands gesendet wird, kommt nach dem Reconnect an; `session_present = 1` |
| R14 | Reconnect ohne Sturm | REC-01 | 10 Gateways verlieren gleichzeitig den Link; erster Reconnect mit stratifiziertem Full Jitter (fester Seed, je Gateway ein Zeitslot) über 5 s, danach exponentieller Backoff mit Jitter. Alle Sessions werden wieder aufgenommen, die Versuche verteilen sich über ≥ 50 % des Fensters |
| R15 | Security-Logs verfügbar, ohne Secrets | LOG-01 (Connect mit Client- und Zertifikatsidentität), LOG-02 (TLS-/Auth-Fehler), LOG-03 (ACL-Ablehnung), LOG-04 (Disconnect), LOG-05 (kein Private Key/Passwort in Broker-Log oder Evidenz) | Treffer im Broker-Log des Laufzeitfensters; LOG-05: keine Treffer |
| R16 | Legacy-Zertifikate ohne Gateway-ID (AWS-IoT-Profil) werden dem richtigen Gateway zugeordnet | *advisory:* LEG-01, LEG-02 | siehe [`legacy-certificates.md`](legacy-certificates.md) |
| R17 | Zertifikatsrotation: Überlappung alt/neu, Wechsel mit Rückfall | *advisory:* ROT-01, ROT-02 | siehe [`legacy-certificates.md`](legacy-certificates.md) |
| R18 | Binäre Payloads byteexakt in beide Richtungen (opak) | PAY-01 | alle 256 Bytewerte plus Rahmenform `[1 Byte][uint32 BE][Body]` kommen unverändert an (`state` und `cmd`) |
| R19 | Last Will bei Linkverlust | *advisory:* LWT-01 | Will auf eigenem `state` wird nach TCP-Abbruch ohne DISCONNECT zugestellt (Einsatz von LWT ist OFFEN) |
| R20 | Abgelaufenes Command (Message Expiry) wird nicht nachgeliefert | *advisory:* EXP-01 | Command mit Expiry 2 s, Gateway 4 s offline: nicht zugestellt; Kontroll-Command ohne Expiry kommt an (Werte OFFEN) |
| R21 | Payload-Größen | *advisory:* PAY-02 (128 B = v1.3-Referenz, 12 KB = historische Annahme), PAY-03 (nur wenn das Profil `max_packet_bytes` setzt: Grenze + 1 Byte wird abgelehnt) | Paketgrenze ist OFFEN (ENTC-61); deshalb keine Pflicht |
| R22 | Broker-Neustart: persistente Session und eingereihtes QoS-1-Command bleiben erhalten | *advisory:* RST-01 (Hook `restart`) | nach dem Neustart `session_present = 1` und Command zugestellt |
| R23 | Widerruf erreicht eine aktive Session | *advisory:* REV-01 (Hook `revoke`) | offene Verbindung des widerrufenen Zertifikats wird beendet **und** neue Verbindungen abgelehnt; nur neue abgelehnt = PARTIAL |
| R24 | ACL-Entzug wirkt auf eine aktive Session | *advisory:* ACL-14 (Hooks `acl-withdraw`, `acl-restore`) | nach dem Entzug kein Publish mehr zugestellt und das bestehende Abo liefert nichts mehr; nur Publish gesperrt = PARTIAL |

**Ergebniswerte:**
- **PASS:** gefordertes Verhalten beobachtet.
- **FAIL:** gegenteiliges Verhalten beobachtet.
- **PARTIAL:** der Zugriff ist faktisch gesperrt, die Ablehnung wird aber nicht signalisiert.
- **INCONCLUSIVE:** keine Evidenz (Setup fehlgeschlagen, Timeout, Positivkontrolle
  fehlgeschlagen, Broker-Log fehlt).
- **Advisory-Fälle** gehen nicht in die Abnahme ein. Sie decken Punkte ab, deren Anforderung
  noch offen ist (ENTC-31/58/61).
- **N/A:** Fall gilt für das gewählte Wire-Profil nicht (z. B. ID-03 unter `lab-eicp`). Er fehlt
  dann nicht, sondern wird im Bericht als „Not applicable“ ausgewiesen.

### Hooks: Änderungen während des Laufs

RST-01, REV-01 und ACL-14 brauchen eine Aktion am Broker mitten im Lauf. Der Harness fordert
sie über Dateien in `results/acceptance-<run>/hooks/` an; `scripts/13_acceptance.sh`
beantwortet sie:

| Hook | Lab-Broker (von `make acceptance` gestartet) | Anderer Broker |
|---|---|---|
| `restart` | `docker compose restart <service>`, wartet auf `ready_log` | `SIM_HOOK_RESTART="<befehl>"` |
| `revoke` | `scripts/17_revoke_live.sh` (widerruft `revoke-live`, neue `crl.pem`), dann Profil `[hooks] crl_reload` | Skript 17, dann `SIM_HOOK_CRL_RELOAD="<befehl>"` |
| `acl-withdraw` / `acl-restore` | ACL-Dateien ohne / mit Gateway C neu schreiben (`enetec_sim acl`), dann Profil `[hooks] acl_reload` | dasselbe, dann `SIM_HOOK_ACL_RELOAD="<befehl>"` |

`crl_reload` / `acl_reload`: `hup` = SIGHUP an den Container, `none` = Broker liest die Datei
selbst nach, `exec:<befehl>` = Befehl im Broker-Container (EMQX: `exec:emqx ctl conf reload --merge`),
fehlt = nicht unterstützt → der Fall bleibt INCONCLUSIVE. Ein
Fall gilt erst als erfüllt, wenn die Änderung innerhalb von `observe_s` wirkt. Nach einem Lauf
mit REV-01 erzeugt der nächste `make acceptance` die Negativ-Identitäten neu (frische CRL).

## 4. Einsatz gegen andere Broker (ENTC-59)

Broker-Profile liegen in `sim/targets/` (`make brokers`):

| Profil | Status | Aufruf |
|---|---|---|
| `mosquitto-lab` | verifiziert, wird per Compose gestartet | `make acceptance` |
| `emqx` | EMQX 5.8 als Lab-Container, wird automatisch gestartet; Log-Muster noch zu bestätigen ([`brokers/emqx/`](../../brokers/emqx/README.md)) | `make acceptance BROKER=emqx` |
| `cedalo` | Pro Mosquitto (Cedalo) als Lab-Container, gleiche ACL wie Mosquitto plus `crlfile`; braucht Lizenz und `docker login registry.cedalo.com`; Vorlage bis zum ersten Lauf ([`brokers/cedalo/`](../../brokers/cedalo/README.md)) | `make acceptance BROKER=cedalo` |

`make simulate BROKER=<profil>` nutzt dasselbe Profil. Host und Port kommen aus dem Profil;
`SIM_BROKER_HOST`/`SIM_BROKER_PORT` überschreiben sie. Aus dem `sim`-Container heraus wird
`localhost` automatisch zu `host.docker.internal`. Jedes Vorlagen-Profil beschreibt im Kopf,
wie der Broker aus `synthetic/fleet.json` zu konfigurieren ist.

Die Fälle bleiben unverändert, nur die Broker-Seite ändert sich:

1. Profil kopieren: `sim/targets/mosquitto-lab.toml` → `sim/targets/<broker>.toml`
   (Name, Host/Port, Beobachtungsfenster, Log-Muster).
2. Broker aus `synthetic/fleet.json` konfigurieren:
   - Lab-CA (`certs/ca/ca.crt`) als Client-CA vertrauen
   - Server-Zertifikat `certs/broker/*` oder ein eigenes, das der Lab-CA vertraut
   - Zertifikats-CN als Identität verwenden (Legacy-Zertifikate ohne CN: Fingerprint-Registry)
   - nur die erlaubte Client-ID je Identität zulassen (`synthetic/client_identities.tsv`)
   - je Gateway nur `write enetec/v1/<clientId>/state` und `read enetec/v1/<clientId>/cmd`
     (fertige Regeln: `mosquitto/config/acl` für Mosquitto und Pro Mosquitto, `brokers/emqx/acl.conf`)
   - Ingest liest nur `state`, Command schreibt nur `cmd`; alles andere wird verweigert
3. Broker-Log des Laufzeitfensters exportieren und über `SIM_BROKER_LOG` übergeben.
4. Für RST-01, REV-01, ACL-14: `SIM_HOOK_RESTART`, `SIM_HOOK_CRL_RELOAD`, `SIM_HOOK_ACL_RELOAD`
   setzen (sonst INCONCLUSIVE, ohne Einfluss auf das Abnahmeergebnis).
5. `make acceptance` mit `SIM_TARGET`, `SIM_BROKER_HOST`, `SIM_BROKER_PORT` und `BROKER_LABEL`.

Der Abschnitt „Broker limitations found“ in `report.md` liefert je Abweichung einen
broker-neutralen Befund. Die Einordnung NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE /
CUSTOM / UNSUPPORTED erfolgt anschließend je Kandidat in der ENTC-59-Matrix.

### Zwei Broker vergleichen

```bash
make compare A=emqx B=mosquitto-lab
make compare A=cedalo B=emqx FRESH=1
make compare
```

Die erste Zeile nimmt den letzten Lauf mit Messwerten je Broker (bevorzugt im aktuellen Wire-Profil), die zweite führt die Abnahme für
beide vorher neu aus, die dritte (ohne Angaben) zeigt Broker und vorhandene Läufe. Läufe ohne
Evidenz (Broker nicht erreichbar, nur INCONCLUSIVE) werden dabei übersprungen.

Das Ergebnis liegt in `results/compare-<A>-vs-<B>-<zeit>/` (`comparison.md`, `comparison.json`,
`summary.txt`) und endet mit einer Zusammenfassung. Der Vergleich nennt nur Fakten:
Ergebnis je Anforderung (R01–R24) nebeneinander, Fälle mit unterschiedlichem Ergebnis samt
Beobachtung, gemeinsame Schwächen und den Aufwand je Anforderung
(NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE / CUSTOM DEVELOPMENT / UNSUPPORTED, aus
dem Abschnitt `[effort]` des Profils). Er wählt keinen Anbieter aus, weil Kosten, Betrieb,
Support und Skalierung nicht Teil der Abnahme sind.

Mit `FRESH=1` bei nicht vom Lab verwalteten Brokern (z. B. Cloud-Instanz) sind
`SIM_BROKER_LOG` bzw. die Profile für den Log-Export nötig; sonst bleiben die LOG-Fälle INCONCLUSIVE.

### Gewichtete Entscheidungsmatrix

```bash
make decide
```

Liest `sim/decision.toml` und den letzten Lauf je Broker-Profil. Ergebnis in
`results/decision-<zeit>/` (`decision.md`, `decision.json`, `summary.txt`).

- **Aus Lab-Evidenz berechnet:**
  - Security-Abnahme: Pflichtfälle PASS = 1, PARTIAL = 0,5, FAIL = 0; INCONCLUSIVE zählt nicht.
    Mehr als 20 % ohne Evidenz → offen.
  - Entwicklungsaufwand: Durchschnitt der Aufwandsklassen `[effort]` des Profils, sofern
    `decision.toml` keinen belegten Wert setzt.
- **Handbewertungen 0–5 mit Pflichtquelle:** HA/Betrieb, Skalierung, GCP-Integration,
  Anbieter-Support, Kosten.
- **Offen ist nicht 0:** Ein Kandidat mit offenem Gewicht bekommt keine Summe. Solange auf der
  Shortlist etwas offen ist, nennt `make decide` keinen Favoriten.
- **Sensitivität:** Wenn ein Favorit feststeht, prüft die Matrix, ob er wechselt, sobald ein
  einzelnes Gewicht um ±50 % geändert wird.
- Die Gewichte sind ein Vorschlag des Labs (ASSUMPTION) und mit SOLHEA/ENETEC abzustimmen.
  Kandidaten: EMQX und Pro Mosquitto (Cedalo); `mosquitto-lab` erscheint als Referenz ohne Rang.
  Handbewertungen sind bisher keine eingetragen: Die Cedalo-Herstellerangaben
  ([`brokers/cedalo/README.md`](../../brokers/cedalo/README.md)) sind recherchiert, aber ungeprüft.

## 5. Referenzergebnisse

### 2026-10-13, Wire-Profil v13 (Docker-Lab, Linux)

| Broker | Ergebnis | Pflichtfälle | Beratend nicht bestanden | Bericht |
|---|---|---|---|---|
| EMQX 5.8.6, `brokers/emqx/emqx.conf` | NOT ACCEPTED | 31/34 PASS, 3 FAIL (ID-01, ID-03, DUP-01) | MTLS-07, MTLS-08, LEG-01, EXP-01 (mit Durable Sessions), REV-01; ACL-14 PARTIAL | [`2026-10-13-emqx-5.8.6-v13.md`](reference/2026-10-13-emqx-5.8.6-v13.md) |
| EMQX 5.8.6 + Registry-Prototyp (`brokers/emqx-registry/`) | **ACCEPTED** | 34/34 PASS | MTLS-07, MTLS-08, LEG-01, EXP-01, REV-01; ACL-14 PARTIAL | [`2026-10-13-emqx-5.8.6-registry-v13.md`](reference/2026-10-13-emqx-5.8.6-registry-v13.md) |
| Mosquitto 2.0.18, Lab-Konfiguration | NOT ACCEPTED | 25/34 PASS, 3 FAIL (ID-01, ID-03, DUP-01), 6 PARTIAL (Subscribe-Ablehnung nicht signalisiert) | MTLS-08, LEG-01, REV-01 | [`2026-10-13-mosquitto-2.0.18-v13.md`](reference/2026-10-13-mosquitto-2.0.18-v13.md) |

Vergleichslauf EMQX ohne Durable Sessions (RST-01 FAIL, EXP-01 PASS):
[`2026-10-13-emqx-5.8.6-v13-ohne-durable-sessions.md`](reference/2026-10-13-emqx-5.8.6-v13-ohne-durable-sessions.md).
Pro Mosquitto (Cedalo) ist noch nicht gelaufen. HiveMQ und Bevywise wurden am 12.10. gestrichen; ihre
Berichte stehen in der Git-Historie.

**RST-01 seit 13.10.:** Der Fall öffnet die Session jetzt wie ein Gateway mit Clean Start = false.
Vorher mit Clean Start = true; Mosquitto schreibt solche Sessions nicht in die Persistenzdatei, deshalb
meldete der Lauf vom 08.10. fälschlich „Session nach Neustart verloren“.

### 2026-10-08, Wire-Profil v13 (lokal, historisch)

Mosquitto 2.0.18 ohne Docker, Hooks über `SIM_HOOK_*`: gleiche Pflichtergebnisse wie am 13.10.,
RST-01 noch mit dem oben beschriebenen Messfehler. Bericht:
[`2026-10-08-mosquitto-2.0.18-v13.md`](reference/2026-10-08-mosquitto-2.0.18-v13.md).

### 2026-09-30, Mosquitto 2.0.18, Profil lab-eicp (historisch)

Vollständiger Bericht: [`reference/2026-09-30-mosquitto-2.0.18.md`](reference/2026-09-30-mosquitto-2.0.18.md).
Der Lauf erfolgte aus einem sauberen Checkout (neue CA, neue Zertifikate). Ein zweiter Lauf
im Arbeitsverzeichnis ergab dieselben Ergebnisse.

**Ergebnis: NOT ACCEPTED** (Exit 1). Pflichtfälle: 23 PASS, 2 FAIL, 6 PARTIAL, 0 INCONCLUSIVE.

| Anforderung | Ergebnis | Kern der Beobachtung |
|---|---|---|
| R01–R03, R05 | PASS | Individuelle Zertifikate werden akzeptiert. Kein Zertifikat, eine gleichnamige fremde CA und ein selbstsigniertes Zertifikat werden per TLS-Alert abgelehnt. Die ACL folgt dem Zertifikat, nicht der Client-ID |
| R04 | PASS (advisory MTLS-08 FAIL) | abgelaufen, noch nicht gültig und falsche EKU werden abgelehnt. Ein widerrufenes Zertifikat wird ohne `crlfile` akzeptiert; mit `crlfile certs/negative/crl.pem` wird es abgelehnt (gegengeprüft) |
| R06 | **FAIL** | CN ≠ Client-ID wird akzeptiert, **die legitime Session von gw-sim-000002 wird verdrängt** (DoS-Vektor). Mosquitto kann CN = Client-ID nicht selbst erzwingen |
| R07, R09, R10 | **PARTIAL** | Unberechtigte PUBLISH werden mit PUBACK 135 abgelehnt und nicht zugestellt. Unberechtigte SUBSCRIBE (fremdes c2d/d2c, Wildcard, falsche Richtung, unbekanntes Gateway) werden mit **SUBACK 1 bestätigt**; zugestellt wird nichts |
| R08 | PASS | nur eigenes d2c beschreibbar, eigenes c2d nicht |
| R11 | **FAIL** | Session-Takeover: Die zweite Verbindung wird angenommen, die bestehende per DISCONNECT (Reason 0) getrennt |
| R12 | PASS | PUBACK 0, Zustellung mit QoS 1. Die beim Linkverlust unbestätigte Nachricht wurde nach dem Reconnect erneut gesendet und 2× zugestellt (ohne DUP-Flag beim Subscriber) |
| R13 | PASS | Ein Command aus der Offline-Phase kommt nach dem Reconnect mit Clean Start = false an. Clean Start = true verwirft es |
| R14 | PASS | 10/10 Sessions wieder aufgenommen, 10 Versuche über 4,2 s, Spitze 3/s |
| R15 | PASS | Connect (mit `u'<CN>'`), TLS-Fehler, `Denied PUBLISH` und Disconnect werden protokolliert; keine Secrets gefunden. Hinweis: TLS-Fehler erscheinen ohne Subject und ohne konkreten Grund |

Das Docker-Lab nutzt `eclipse-mosquitto:2` (beim letzten Lauf 2.1.2). `make acceptance` sollte
dort wiederholt werden; insbesondere das SUBACK-Verhalten ist versionsabhängig zu bestätigen.

## 6. Grenzen

- **Nicht abgedeckt:**
  - HA-Failover (RST-01 prüft nur den Neustart eines Knotens)
  - Bootstrap-ACL-Phase
  - Applikationskorrelation `command_id` ↔ `origin_command_id` (braucht Firmware, kein Broker-Thema)
  - Skalierung auf ~15.000 Verbindungen und GCP-Pub/Sub-Anbindung (getrennt von der
    funktionalen Abnahme zu berichten)

  Bestehende Einzeltests im Profil `lab-eicp`: ACL-Änderung bei aktiver Session (Test 10),
  Gateway-Austausch (Test 09).
- **Linkverlust** wird als TCP-Close ohne DISCONNECT simuliert. Stille Verluste (Erkennung erst
  über Keep-alive) bräuchten `tc`/`iptables`.
- **Negativbeobachtungen** gelten für das Beobachtungsfenster (`observe_s`, Standard 3 s);
  eine spätere Zustellung ist damit nicht ausgeschlossen.
- **Log-Prüfungen** sind Mustersuchen je Broker-Profil: Sie zeigen, dass Einträge vorhanden
  sind, nicht dass sie vollständig sind.

Weitere Evidenz zu Sessions und Volumen unter realistischem Traffic liefert die
Architektur-Simulation: [`synthetic-simulation.md`](synthetic-simulation.md).
