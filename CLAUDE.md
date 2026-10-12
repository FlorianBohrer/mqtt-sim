# CLAUDE.md – mqtt-sim (ENETEC MQTT-Lab)

Ausführliches Playbook: [`docs/AI-PLAYBOOK.md`](docs/AI-PLAYBOOK.md). Diese Datei ist die Kurzfassung für jede Session.

## Was das ist
Labor für die MQTT-Kommunikation Gateway ↔ Broker (ENETEC, Umzug AWS IoT → GCP): Acceptance-Harness
(ENTC-63), synthetische Flotte und Simulation, Broker-Vergleich und Entscheidungsmatrix (ENTC-59),
Baukasten-Webseite `web/baukasten/index.html`. Doku auf Deutsch (`docs/MQTT-SIM-ENV.md`, englisch `.en.md`).

## Regeln
- Semantik nur aus ENTC-61 / MQTT wire contract v1.3; Offenes bleibt OFFEN (Client-ID-Algorithmus,
  Paketgrenze, Widerruf, Session-Werte, Regel bei doppelter Client-ID). Nichts erfinden, Platzhalter kennzeichnen
  (SOURCE / INTERPRETED / ASSUMPTION / OPEN).
- Broker-Verhalten nur aus Läufen in `docs/mqtt-tests/reference/`. Ergebnisse nie von Hand eintragen.
- Harness-Prinzipien: Zeuge statt PUBACK, Positivkontrolle MTLS-01, unerreichbar ≠ abgelehnt, INCONCLUSIVE ≠ PASS.
- Generierte Dateien nicht von Hand ändern: `synthetic/`, Broker-ACLs, `brokers/bevywise/generated/`,
  Datenblock der Webseite. Generator ändern, dann `make fleet` bzw. `make web`.
- `WIRE=lab-eicp` muss das alte Schema byte-identisch erzeugen; neue Optionen ändern bestehende Ausgaben nicht.
- Keine Geheimnisse, keine Lauf-Ergebnisse, kein `sim/config.local.toml` committen.
- Entscheidungen (Broker-Wahl, Matrix-Gewichte, OFFENE Spec-Punkte, Merge nach `main`) trifft der Mensch.

## Befehle
- Tests: `cd sim && python3 -m unittest discover -s tests -t .` (Container: `make sim-test`)
- Ohne Docker: `SIM_LOCAL=1 make fleet | make web | make acceptance …` (Python ≥ 3.11, paho-mqtt 2.1)
- Abnahme: `make acceptance [BROKER=emqx] [WIRE=lab-eicp]`; Vergleich: `make compare A=… B=…`; Matrix: `make decide`
- Webseite: `make web` (Daten neu), dann `web/baukasten/index.html` im Browser öffnen

## Vor jedem Commit
Tests grün, generierte Dateien aktuell, Doku DE/EN nachgezogen, `VERSION` erhöht bei Nutzer-sichtbaren
Änderungen, keine Schlüssel im Diff, in der Antwort sagen, was nicht getestet wurde.
