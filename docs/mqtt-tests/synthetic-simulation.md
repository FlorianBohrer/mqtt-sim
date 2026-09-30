# Synthetische ENETEC-Flotte und Architektur-Simulation

**Stand:** 2026-09-30 · **Bezug:** ENTC-63 (primär), ENTC-58, ENTC-59 · **Semantik-Quelle:** ENTC-61 / EICP v1.4

Dieses Dokument beschreibt die synthetischen Daten und die Architektur-Simulation für die
Kommunikationsschicht **Gateway ↔ MQTT-Broker**. Die Sicherheits- und Abnahmetests (ENTC-63)
nutzen dieselbe Flotte und PKI und sind in [`acceptance-harness.md`](acceptance-harness.md)
beschrieben.

---

## 1. Zweck und Abgrenzung

- **Ziel:** eine realistische, deterministisch reproduzierbare Flotte mit passendem Traffic,
  um Sicherheit und Broker-Verhalten (mTLS, Identität, ACL, QoS 1, Sessions, Reconnect)
  gegen beliebige Broker zu prüfen.
- **Nicht im Scope:** Data Lake, BigQuery, Payload-Verarbeitung, OTA und Bootstrap/Claim.
- **Keine erfundene Nachrichtensemantik.** Die einzige konkrete Nachricht ist
  `telemetry.report` im Format von `samples/telemetry.json`. Commands laufen bewusst im
  Lab-Namespace `c2d/simulation/command` mit neutralem Payload und tragen keine
  EICP-Command-Semantik.
- **Kennzeichnung** wie in ENETEC.md: `SOURCE` (Projektunterlage), `INTERPRETED`
  (daraus abgeleitet), `ASSUMPTION` (Lab-Annahme), `OPEN` (Entscheidung ausstehend).

## 2. Aufbau der Simulation

```text
 Peripheral Devices  (nur als Daten: Seriennummer, Geräteklasse, Raumklima)
        │ lokal (RS-485/Thread/…), nicht simuliert
        ▼
 GatewaySim × N ── MQTT 5 + mTLS, Client-ID = Zertifikats-CN = Gateway-ID ──► Broker
   • d2c telemetry/report, QoS 1                                           (Lab: Mosquitto;
   • c2d/# abonniert, QoS 1                                                 später EMQX,
   • Netzabbruch = TCP-Close ohne DISCONNECT                                HiveMQ, Bevywise)
   • Offline-Puffer, Reconnect mit Clean Start = false                          │ ACL generiert,
                                                                                │ deny by default
                                        svc-sim-cloud-ingest  ◄── liest d2c ────┤ (≙ MQTT→Pub/Sub-Bridge)
                                        svc-sim-cloud-command ──► schreibt c2d ─┘ (≙ Backend-Command-Pfad)
```

Jeder Akteur hat ein eigenes Zertifikat der Lab-CA. Die Cloud-Platzhalter haben nur je
eine Richtung, ein Gateway hat nur Schreibrechte auf `…/d2c/#` und Leserechte auf `…/c2d/#`
im eigenen Plant-/Gateway-Pfad.

## 3. Datenmodell und Quellen

| Aspekt | Umsetzung | Kennzeichnung |
|---|---|---|
| Topic-Schema | `eicp/v1/sim/{plantId}/gateways/{gatewayId}/{d2c\|c2d}/{domain}/{operation}` | SOURCE (EICP) |
| Plant-ID | neue Plants `plt_<UUIDv7>`; `plt_sim_001/002` bleiben für die Skripte 04–10 erhalten | SOURCE / Lab-Kompatibilität |
| Gateway-ID | `gw-sim-NNNNNN` (Lab-Konvention); das echte Format ist offen | OPEN |
| Identität | Zertifikats-CN == MQTT-Client-ID == Gateway-ID | SOURCE (EICP v1.4) |
| Device-ID | `deviceId` = 32-Bit-Hardware-Seriennummer, keine zusätzliche ID | SOURCE (ENETEC.md §5.5) |
| Gateway-Typen | SmartComfort365, Pure365 Bridge (Verteilung 60/40) | SOURCE (Mental Model v1.0) / ASSUMPTION |
| Topologie | je Gateway: 1 Systemregler, 3–16 Raumgeräte, 0–2 I/O-Module; Wohnobjekt 1 Gateway, Gewerbe 2–3 | INTERPRETED |
| Telemetrie | nur Raumgeräte, Felder `temperatureC`, `humidityPct`, `co2Ppm` (Lab-Sample) | SOURCE (Lab) |
| Volumen | kalibriert auf ~251 D2C/Gateway/Tag (2,51 Mio. ÷ ~10.000) | SOURCE (Planungswert) |
| Volumen-Mix | alles als Telemetrie modelliert; Anteile von State/Heartbeat/Event sind offen | ASSUMPTION / OPEN |
| MQTT | MQTT 5, QoS 1, Keep-alive 120 s, Clean Start = false beim Reconnect | SOURCE |
| Session Expiry | 3600 s | ASSUMPTION / OPEN |
| Zeitstempel | `timestamp` = Erzeugungszeit (Unix s, Gateway-Uhr mit Drift), `measuredAt` = Messzeit, bleibt beim Nachsenden erhalten | SOURCE (EICP §8.7) |
| Zeitformat | Lab-Sample nutzt ISO 8601 für `measuredAt`, EICP nennt Unix-Sekunden | **OPEN, mit ENTC-61 klären** |
| Ausfälle | stabil 0,02/h, instabil 0,5/h (25 % der Gateways), Dauer 20–900 s, Reconnect-Jitter 0,5–30 s | ASSUMPTION |
| Ereignisse | „regional-isp-outage“ (50 % der Gateways, 15 min → Reconnect-Sturm), „overnight-outage“ (4 h → Pufferüberlauf) | ASSUMPTION (Edge Cases aus MQTT Current State §10) |
| Offline-Puffer | 50 Nachrichten, bei Überlauf werden die ältesten verworfen, Nachsenden mit 10 msg/s | ASSUMPTION |
| In-flight-Abbruch | 30 % der Ausfälle treffen eine unbestätigte QoS-1-Nachricht | ASSUMPTION |
| Nicht simuliert | LWT/presence/heartbeat, Bootstrap-Namespace, OTA, Nutzlasten bis 12 KB | OPEN |

Alle Parameter stehen in [`sim/config.toml`](../../sim/config.toml). Der Generator ist deterministisch
(Seed, eigener Zufallsstrom je Gateway und Device).

## 4. Standarddatensatz (`synthetic/`)

| Kennzahl | Wert |
|---|---:|
| Plants / Gateways / Devices | 6 / 10 / 108 (91 Raumgeräte) |
| Zeitfenster | 24 h ab 2026-10-01T00:00Z (Do., Ortszeit UTC+2) |
| Telemetrie erzeugt / gesendet | 2.516 / 2.500 |
| je Gateway und Tag | 251,6 (Planungswert 251) |
| gepuffert und nachgesendet / durch Überlauf verworfen | 113 / 16 |
| Offline-Fenster / betroffene Gateways | 57 / 6 (davon 12 In-flight-Abbrüche) |
| Commands / davon während eines Ausfalls | 115 / 60 |
| Payload Ø / max | 304 B / 306 B (Planung: Ø 500 B, max ~12 KB) |

Dateien:

- `synthetic/fleet.json`: Registry mit Plants, Gateways (ID, Plant, Typ, Seriennummer,
  Zertifikats-CN, Client-ID, Topics, Anbindung, Uhrendrift) und Devices.
- `synthetic/dataset/telemetry.jsonl`: eine Zeile je Nachricht mit Sende- und Erzeugungszeit,
  Topic, `buffered`/`dropped` und vollständigem Envelope.
- `synthetic/dataset/commands.jsonl`, `connectivity.json` (Offline-Fenster je Gateway),
  `summary.json` (Kennzahlen).
- `mosquitto/config/acl`: aus der Flotte generiert. Die Blöcke für gw-sim-000001/000002 sind
  unverändert, damit die Tests 04–10 weiter passen.

Ein Unit-Test stellt sicher, dass die eingecheckten Dateien exakt der Konfiguration entsprechen.
Nach einer Änderung an `sim/config.toml` also `make fleet` ausführen und das Ergebnis committen.

## 5. Ablauf

```bash
make init            # Lab-CA, Broker-Zertifikat, gw-sim-000001/2 (unverändert)
make fleet           # Flotte, Datensatz, ACL + Zertifikate für alle Gateways und Services
make up              # Mosquitto (lädt die generierte ACL)
make simulate        # 24-h-Datensatz x720 (~2 min) -> results/simulation-<run>/
make acceptance      # ENTC-63-Abnahme (siehe acceptance-harness.md)
make sim-test        # Unit-Tests im Container
```

- Python läuft im Compose-Service `sim` (python:3.12-alpine + paho-mqtt 2.1.0). Eine lokale
  Python-Installation ist nicht nötig.
- Ohne Docker für Python: `SIM_LOCAL=1 make simulate` (python3 ≥ 3.11 und `pip install -r sim/requirements.txt`).
- Optionen: `SPEED=2880 GATEWAYS=gw-sim-000001,gw-sim-000006 make simulate`.
- Integrationstests gegen einen lokal installierten Mosquitto:
  `cd sim && python3 -m unittest tests.test_broker_integration -v`.
- Simulation und Abnahme nutzen die echten Client-IDs. Sie sollten nicht parallel zueinander
  oder zu den Tests 09/10 laufen.

## 6. Auswertung der Simulation

Der Datensatz wird zeitgerafft abgespielt: Plan-Sekunden × 1/SPEED. `verify` vergleicht die
Beobachtung mit dem Plan. Exit-Codes: `0` = PASS, `1` = FAIL, `2` = Lauf unvollständig
(INCONCLUSIVE).

| Check | Regel |
|---|---|
| `all_planned_published` | jede nicht verworfene Plan-Nachricht wurde publiziert |
| `puback_all_success` | jeder PUBLISH erhielt PUBACK < 128 |
| `d2c_complete` | jede erwartete `messageId` kam beim Cloud-Ingest an (Duplikate sind bei QoS 1 zulässig und werden gezählt) |
| `d2c_no_unexpected` | keine Nachricht, die laut Plan verworfen oder unbekannt ist |
| `d2c_topic_identity_consistent` | Topic-Plant/-Gateway == `gatewayId` im synthetischen Envelope == Flotten-Registry |
| `c2d_complete` | jedes Command erreichte sein Gateway, auch wenn es während eines Ausfalls gesendet wurde (persistente Session) |
| `c2d_only_to_addressed_gateway` | kein Command bei einem fremden Gateway |
| `session_resumed_after_every_outage` | jeder Reconnect mit Clean Start = false liefert `session_present = 1` |
| `no_unplanned_disconnects` | keine Trennung außer geplanten Ausfällen und Shutdown |

- Nachrichten früherer Läufe werden über die MQTT-5-User-Property `sim-run` erkannt und nur gezählt.
- Die Auswertung liest nur die Felder `messageId`, `gatewayId` und `sequenceNumber` des
  **eigenen synthetischen Envelopes**; es gibt keine Applikationslogik.
- PUBACK und Zustellung sind Nachweise auf Transportebene: **MQTT PUBACK ≠ EICP-Applikations-ACK**.
- Evidenz: `run.json`, `events.jsonl`, `report.json`, `summary.txt`, `broker.log`.

## 7. Referenzlauf 2026-09-30 (Mosquitto 2.0.18, lokal, Lab-Konfiguration): PASS

- **D2C:** 2.500/2.500 Nachrichten zugestellt (0 fehlend, 0 unerwartet, alle PUBACK 0),
  davon 113 aus dem Offline-Puffer nachgesendet.
- **C2D:** 115/115 Commands zugestellt, davon 60/60 während eines Ausfalls über die
  persistente Session.
- **Sessions:** 57/57 Reconnects mit `session_present`, 0 ungeplante Trennungen.
- **Duplikate:** 11 Nachrichten waren beim Linkverlust unbestätigt und kamen **doppelt** an,
  jeweils ohne DUP-Flag beim Subscriber, weil das Flag nur pro Hop gilt.
- **Latenz lokal:** p50 0,7 ms, p95 2,0 ms.

**Befunde:**
- Die Deduplizierung muss über `messageId` im IoT Integration Layer erfolgen (ENETEC.md §9);
  DUP-Flags sind dafür ungeeignet.
- Gepufferte Telemetrie kommt mit dem ursprünglichen `measuredAt` und späterem `timestamp` an.
  Die Cloud darf damit keinen neueren State überschreiben (ENETEC.md §10.4).

## 8. Grenzen und nächste Schritte

- **Skalierung:** ein Thread je Gateway, geeignet für einige hundert Gateways. Der Generator
  skaliert (z. B. `fleet.plants = 6000`), aber für ~15.000 Verbindungen braucht es ein eigenes
  Lastwerkzeug (Priority 4); die Zertifikatserzeugung über `02_create_gateway.sh` ist dafür zu langsam.
- **Zeitraffung:** Broker-Timer (Keep-alive, Session Expiry) laufen in Echtzeit. Ein
  Session-Ablauf bei langen Ausfällen wird deshalb nicht abgebildet.
- **Netzabbruch** = TCP-Close. Stille Verbindungsverluste (Erkennung erst über Keep-alive, LWT)
  bräuchten `tc`/`iptables` im Container.
- **Payload-Größen** sind nicht auf Ø 500 B / max 12 KB kalibriert; Größen- und Oversize-Tests
  folgen mit dem Lasttest.
- **Nächste Schritte:**
  - Datensatz und Simulation gegen die ENTC-59-Kandidaten laufen lassen (gleiche Flotte, gleiche Checks).
  - Anschließend die MQTT→Pub/Sub-Bridge anstelle von `svc-sim-cloud-ingest` anbinden.
