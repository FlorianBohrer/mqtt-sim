# ENTC-63 – MQTT Security & Broker Acceptance Harness

**Stand:** 2026-09-30 · **Bezug:** ENTC-63, Eingabe für ENTC-58, ENTC-59 und ENTC-31 · **Semantik-Quelle:** ENTC-61 / EICP v1.4

Der Harness macht aus dem Docker/Mosquitto-PoC eine wiederholbare, broker-agnostische
Abnahmesuite für die Kommunikation **Gateway ↔ MQTT-Broker**. Er prüft Transport- und
Sicherheitsverhalten mit simulierten Gateways und liefert deterministische PASS/FAIL-Evidenz
je Anforderung. Die Payloads sind opake Zufallsbytes: Es wird keine ENETEC-Command-Semantik
implementiert und keine Applikations-Payload dekodiert.

---

## 1. Verifikationsbefehl

```bash
make acceptance        # = scripts/13_acceptance.sh
```

- **Exit 0 nur dann, wenn jeder Pflichtfall PASS ist.** Andernfalls Exit 1, also auch bei
  FAIL, PARTIAL, INCONCLUSIVE oder einem unvollständigen/gefilterten Lauf.
- **Aus sauberem Stand reproduzierbar:** `make clean && make acceptance`. Das Skript erzeugt
  die fehlenden Voraussetzungen selbst:
  1. Lab-CA und Broker-Zertifikat (`01`)
  2. synthetische Flotte mit individuellen Gateway- und Service-Zertifikaten sowie generierter ACL (`11`)
  3. Negativ-Identitäten, bei jedem Lauf neu aus der aktuellen CA (`12`)
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
| Gateway A | `gw-sim-000001` (Plant `plt_sim_001`) | Akteur; Negativ-Zertifikate tragen seine ID |
| Gateway B, C | `gw-sim-000002`, `gw-sim-000003` (beide `plt_sim_002`) | Ziel für Cross-Plant (A→B) und Cross-Gateway im selben Plant (C→B) |
| Cloud-Ingest | `svc-sim-cloud-ingest` (liest alle d2c) | Zeuge für Zustellung von d2c-Nachrichten |
| Cloud-Command | `svc-sim-cloud-command` (schreibt alle c2d) | autorisierter Sender in c2d-Namespaces |
| Negativ | `certs/negative/*` | ohne Zertifikat, fremde CA (gleicher Name), selbstsigniert, abgelaufen, noch nicht gültig, falsche EKU, widerrufen, unbekannte Gateway-ID |
| Reconnect | die ersten 10 Gateways der Flotte | gleichzeitiger Linkverlust |

Alle Schlüssel und Zertifikate sind test-only und werden lokal erzeugt. `certs/` ist per
`.gitignore` ausgeschlossen; es werden keine Produktionszertifikate, Cloud-Credentials oder
Geräte-Secrets eingecheckt.

**Messprinzip:** Eine Freigabe oder Sperre wird nicht nur am Return-Code (PUBACK/SUBACK)
erkannt, sondern an der **tatsächlichen Zustellung**. Ein autorisierter Zeuge beobachtet,
ob eine opake Nachricht ankommt. Jeder Fall nutzt eigene Topics unter
`…/{d2c|c2d}/simulation/<run>/<case>` und eigene Zufalls-Payloads.

## 3. Anforderungen und Fälle

| Req. | Anforderung (ENTC-63) | Fälle | PASS-Regel |
|---|---|---|---|
| R01 | mTLS mit individuellem X.509-Zertifikat je Gateway | MTLS-01 | A, B, C verbinden mit eigenem Zertifikat (Client-ID = CN), CONNACK 0, 3 verschiedene Zertifikate. **Positivkontrolle:** ohne sie wird jedes andere PASS zu INCONCLUSIVE |
| R02 | ohne Client-Zertifikat abgelehnt | MTLS-02 | TLS-Alert, CONNACK ≥ 128 oder Abbruch vor CONNACK. „Nicht erreichbar“ zählt nie als Ablehnung |
| R03 | nicht vertrauenswürdige CA abgelehnt | MTLS-03 (fremde CA mit identischem CA-Namen), MTLS-04 (selbstsigniert) | wie R02 |
| R04 | ungültige Zertifikate abgelehnt | MTLS-05 (abgelaufen), MTLS-06 (noch nicht gültig); *advisory:* MTLS-07 (EKU, Profil offen – ENTC-31), MTLS-08 (Widerruf, Strategie offen – ENTC-58/31) | wie R02 |
| R05 | Zertifikatsidentität an Gateway-ID gebunden | ID-02 | Mit A's Zertifikat und B's Client-ID bleibt B's Namespace gesperrt (oder die Verbindung wird abgelehnt) |
| R06 | Client-ID = Gateway-ID erzwungen, sonst Limitierung dokumentiert | ID-01 | Zertifikat A + Client-ID B wird abgelehnt. Andernfalls FAIL mit Nachweis, ob die legitime Session von B verdrängt wurde |
| R07 | Deny-by-default | ACL-06 (Topic außerhalb jedes Namespace), ACL-13 (gültige Kette, unbekannte Gateway-ID) | PUBACK/SUBACK ≥ 128 (oder Trennung) und keine Zustellung |
| R08 | Publish nur in eigenes d2c | ACL-01 (eigenes d2c, Positivkontrolle), ACL-05 (eigenes c2d = falsche Richtung) | ACL-01: PUBACK < 128 und zugestellt; ACL-05: abgelehnt und nicht zugestellt |
| R09 | Subscribe nur auf eigenes c2d | ACL-07 (eigenes c2d, Positivkontrolle), ACL-10 (eigenes d2c = falsche Richtung) | ACL-07: SUBACK < 128 und Command zugestellt; ACL-10: nichts zugestellt und SUBACK ≥ 128 |
| R10 | Cross-Plant/Cross-Gateway gesperrt | ACL-02/-03 (Publish in fremdes d2c, anderes/gleiches Plant), ACL-04 (eigene ID unter fremdem Plant), ACL-08/-09 (Subscribe fremdes c2d), ACL-11 (fremdes d2c mitlesen), ACL-12 (Wildcard `eicp/v1/sim/#`) | keine Zustellung **und** Ablehnung signalisiert |
| R11 | Doppelte Client-ID übernimmt nicht still die aktive Session | DUP-01 | zweite Verbindung abgelehnt **und** die bestehende publiziert danach weiter |
| R12 | QoS 1 | QOS-01 (PUBACK + Zustellung mit QoS 1), QOS-02 (Link bricht nach PUBLISH und vor PUBACK ab, Reconnect mit Clean Start = false) | QOS-02: Session vorhanden, PUBACK nach Reconnect, mindestens eine Zustellung (Duplikate zulässig und gezählt) |
| R13 | Clean Start = false / persistente Session | SES-01; *advisory:* SES-02 (Clean Start = true verwirft die Session) | Command, das während des Offline-Zustands gesendet wird, kommt nach dem Reconnect an; `session_present = 1` |
| R14 | Reconnect ohne Sturm | REC-01 | 10 Gateways verlieren gleichzeitig den Link; erster Reconnect mit stratifiziertem Full Jitter (fester Seed, je Gateway ein Zeitslot) über 5 s, danach exponentieller Backoff mit Jitter. Alle Sessions werden wieder aufgenommen, die Versuche verteilen sich über ≥ 50 % des Fensters |
| R15 | Security-Logs verfügbar, ohne Secrets | LOG-01 (Connect mit Client- und Zertifikatsidentität), LOG-02 (TLS-/Auth-Fehler), LOG-03 (ACL-Ablehnung), LOG-04 (Disconnect), LOG-05 (kein Private Key/Passwort in Broker-Log oder Evidenz) | Treffer im Broker-Log des Laufzeitfensters; LOG-05: keine Treffer |

**Ergebniswerte:**
- **PASS:** gefordertes Verhalten beobachtet.
- **FAIL:** gegenteiliges Verhalten beobachtet.
- **PARTIAL:** der Zugriff ist faktisch gesperrt, die Ablehnung wird aber nicht signalisiert.
- **INCONCLUSIVE:** keine Evidenz (Setup fehlgeschlagen, Timeout, Positivkontrolle
  fehlgeschlagen, Broker-Log fehlt).
- **Advisory-Fälle** gehen nicht in die Abnahme ein. Sie decken Punkte ab, deren Anforderung
  noch offen ist (ENTC-31/58).

## 4. Einsatz gegen andere Broker (ENTC-59)

Die Fälle bleiben unverändert, nur die Broker-Seite ändert sich:

1. Profil kopieren: `sim/targets/mosquitto-lab.toml` → `sim/targets/<broker>.toml`
   (Name, Host/Port, Beobachtungsfenster, Log-Muster).
2. Broker aus `synthetic/fleet.json` konfigurieren:
   - Lab-CA (`certs/ca/ca.crt`) als Client-CA vertrauen
   - Server-Zertifikat `certs/broker/*` oder ein eigenes, das der Lab-CA vertraut
   - Zertifikats-CN als Identität verwenden
   - je Gateway nur `write …/d2c/#` und `read …/c2d/#` im eigenen Plant/Gateway-Pfad
   - Ingest liest nur d2c, Command schreibt nur c2d; alles andere wird verweigert
3. Broker-Log des Laufzeitfensters exportieren und über `SIM_BROKER_LOG` übergeben.
4. `make acceptance` mit `SIM_TARGET`, `SIM_BROKER_HOST`, `SIM_BROKER_PORT` und `BROKER_LABEL`.

Der Abschnitt „Broker limitations found“ in `report.md` liefert je Abweichung einen
broker-neutralen Befund. Die Einordnung NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE /
CUSTOM / UNSUPPORTED erfolgt anschließend je Kandidat in der ENTC-59-Matrix.

## 5. Referenzergebnis: Mosquitto 2.0.18 mit Lab-Konfiguration

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
  - Widerruf aktiver Sessions (MTLS-08 prüft nur neue Verbindungen)
  - Broker-Neustart/HA-Failover
  - Bootstrap-ACL-Phase
  - LWT
  - Payload-Grenzen (12 KB/Oversize)
  - Skalierung auf ~15.000 Verbindungen

  Bestehende Einzeltests: ACL-Änderung bei aktiver Session (Test 10), Gateway-Austausch (Test 09).
- **Linkverlust** wird als TCP-Close ohne DISCONNECT simuliert. Stille Verluste (Erkennung erst
  über Keep-alive) bräuchten `tc`/`iptables`.
- **Negativbeobachtungen** gelten für das Beobachtungsfenster (`observe_s`, Standard 3 s);
  eine spätere Zustellung ist damit nicht ausgeschlossen.
- **Log-Prüfungen** sind Mustersuchen je Broker-Profil: Sie zeigen, dass Einträge vorhanden
  sind, nicht dass sie vollständig sind.

Weitere Evidenz zu Sessions und Volumen unter realistischem Traffic liefert die
Architektur-Simulation: [`synthetic-simulation.md`](synthetic-simulation.md).
