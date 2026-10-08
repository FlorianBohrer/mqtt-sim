# Bevywise MQTTRoute / CrystalMQ für den ENTC-63-Harness

**Stand:** 2026-10-08 · **Bezug:** ENTC-59 (Broker-Vergleich), ENTC-63 (Abnahme)

Diese Konfiguration bindet einen Bevywise-Broker so an, dass `make acceptance BROKER=bevywise`
dieselben Fälle wie beim Lab-Mosquitto prüft. Grundlage ist die öffentliche Bevywise-Dokumentation
([Help](https://www.bevywise.com/mqtt-broker/help.html), [Security](https://www.bevywise.com/mqtt-broker/mqtt-security.html),
[REST-API](https://www.bevywise.com/mqtt-broker/mqtt-broker-api.html)).

- **[DOK]** markiert dokumentierte Schlüssel.
- **[OFFEN]** markiert Punkte, die nicht dokumentiert gefunden wurden. Sie sind mit Bevywise zu
  klären oder vom Harness zu messen.

Gegen einen echten Bevywise-Broker ist die Konfiguration **noch nicht gelaufen**.

## Dateien

| Datei | Zweck |
|---|---|
| `conf/broker.conf.example` | TLS/mTLS-Schlüssel und Zertifikatsablage |
| `conf/mqtt.conf.example` | Topic-ACL, Hinweise zu Auth-Hook, Sessions, doppelter Client-ID |
| `generated/acl-requests.json` | aus `synthetic/fleet.json` erzeugt: eine ACL-Regel je Client-ID (`make bevywise-config`); seit 2026-10-08 mit v1.3-Topics `enetec/v1/{clientId}/state\|cmd` und abgeleiteten Client-IDs |
| `apply-acl.sh` | spielt die Regeln über `POST /crystalmq/api/v1/acl` ein (`DRY_RUN=1` zeigt sie nur an) |
| `../../sim/targets/bevywise.toml` | Harness-Profil (Host, Port, Server-CA, Log-Muster) |

## Schnellweg: Bevywise installieren und mit einem anderen Broker vergleichen

1. Bevywise MQTTRoute von der Bevywise-Downloadseite installieren und einmal starten.
2. Paket erzeugen: `make init && make fleet && make bevywise-bundle`. Läuft der Broker nicht lokal,
   sondern unter einem eigenen Namen: `make bevywise-bundle BEVYWISE_HOST=<name-oder-ip>`.
   Das Paket liegt in `brokers/bevywise/generated/bundle/` (Zertifikate, Konfigurationswerte, ACL-Regeln)
   und wird nicht eingecheckt, weil es einen Lab-Schlüssel enthält.
3. Ordner `Certificate/root` und `Certificate/server` aus dem Paket in den Ordner `Certificate/` der
   Installation kopieren. Werte aus `conf/*.example` in `broker.conf` und `mqtt.conf` übernehmen
   (TLS an, Port 8886, `TOPIC_ACL = TRUE`) und den Broker neu starten.
4. ACL einspielen: `BEVYWISE_API_URL=https://<host>:<api-port> ./brokers/bevywise/apply-acl.sh`.
5. In `sim/targets/bevywise.toml` bei Bedarf `host` eintragen (Port 8886 ist voreingestellt).
6. Abnahme und Vergleich: `make compare A=bevywise B=emqx FRESH=1`. Für die Log-Fälle zusätzlich
   `SIM_BROKER_LOG=<Pfad zum Bevywise-Log>` setzen; ohne Log bleiben LOG-01…05 INCONCLUSIVE.

Ein offizielles Docker-Image von Bevywise gibt es nach meiner Recherche nicht (nur ein nicht
dokumentiertes Fremd-Image), deshalb wird der Broker nicht vom Lab gestartet.

## Einrichtung im Detail

1. **Lab-Identitäten erzeugen:** `make init && make fleet && make negative-certs && make legacy-certs`.
2. **Zertifikate in den Broker kopieren:**
   - `certs/ca/ca.crt` → `Certificate/root/root.crt`
   - Server-Zertifikat und -Schlüssel → `Certificate/server/server.crt` / `server.key`.
     Der SAN muss den Hostnamen aus dem Profil enthalten. Mit der Lab-CA geht das z. B. per
     `scripts/01_create_ca_and_broker.sh`-Muster mit eigenem `DNS.x`.
3. **Konfiguration übernehmen:** Die Werte aus `conf/*.example` in die `broker.conf` / `mqtt.conf`
   der Installation eintragen und den Client-Zertifikats-Pflichtmodus („strict“) aktivieren.
   Anschließend den Broker neu starten.
4. **ACL einspielen:**
   ```bash
   make bevywise-config
   BEVYWISE_API_URL=https://<broker>:<api-port> BEVYWISE_API_AUTH="Authorization: Bearer <token>" \
     ./brokers/bevywise/apply-acl.sh
   ```
5. **Profil `sim/targets/bevywise.toml` anpassen:** `host`, `port`, `server_ca`, und nach dem
   ersten Lauf die Log-Muster aus einem echten Log ergänzen.
6. **Abnahme starten:**
   ```bash
   make acceptance BROKER=bevywise SIM_BROKER_LOG=/pfad/zum/bevywise.log
   ```

## Erwartete Knackpunkte

Aus der Doku abgeleitet; der Harness liefert dazu Belege.

| Anforderung | Fall | Laut Doku | Erwartung |
|---|---|---|---|
| Deny-by-default | ACL-06, ACL-13 | `TOPIC_ACL = TRUE` erlaubt alle Topics, für die keine Regel existiert | **FAIL**, solange kein globaler Deny-Default existiert |
| Identität = Zertifikat | ID-01, ID-02 | ACL ist an **Client-ID oder Username** gebunden. Im Zertifikatsmodus prüft der Broker laut Doku „CN und Client-IP“ | Wenn CN ≠ Client-ID nicht abgelehnt wird, erbt ein beliebiges gültiges Zertifikat die Rechte einer fremden Client-ID → **kritisch** |
| Abgeleitete Client-ID (v13) | ID-03 | Client-ID ist ein Pseudonym der Seriennummer, nicht der CN; die Zuordnung steht in `synthetic/client_identities.tsv` | braucht den Custom-Auth-Hook mit Registry-Abfrage; Bevywise schätzt für Zertifikatszuordnung/Widerruf 4–6 Wochen Zusatzentwicklung (Current State 08.10) |
| Legacy ohne CN | LEG-01 | Custom-Auth-Hook (`AUTHENTICATION = CUSTOM`, `custom_authenticate()`) | ob der Hook das Zertifikat sieht: OFFEN |
| Doppelte Client-ID | DUP-01 | nicht dokumentiert gefunden | wird gemessen |
| Persistente Session / QoS 1 | SES-01, QOS-01/02 | MQTT 5 laut Produktbeschreibung | wird gemessen |
| Audit-Log | LOG-01…04 | Log-Format nicht dokumentiert gefunden | Muster nach dem ersten Lauf ergänzen |

## Fragen an Bevywise

Ergänzend zur bestehenden Fragenliste (MQTT Current State §8):

1. Wie heißt der Schlüssel für das Pflicht-Client-Zertifikat (strict mode)? Welche TLS-Versionen
   und welche Cipher sind einstellbar?
2. Kann der Broker **CN (oder SAN) == Client-ID** erzwingen und eine Abweichung mit CONNACK ablehnen?
3. Gibt es einen **globalen Deny-Default** für die Topic-ACL? Bedeutet `publish_access = allow`
   mit Topic-Liste „nur diese Topics“ oder „diese zusätzlich“?
4. Erhält der Custom-Auth-Hook das Client-Zertifikat (Fingerprint, Seriennummer, Subject) für eine
   Registry-Zuordnung bei Zertifikaten ohne CN?
5. Wie verhält sich der Broker bei doppelter Client-ID? Lässt sich „neue Verbindung ablehnen“ einstellen?
6. Wie sieht das Log für Connect, TLS-Fehler, ACL-Ablehnung und Disconnect aus (Beispielzeilen)?
   Unterstützt der Broker CRL/OCSP?
