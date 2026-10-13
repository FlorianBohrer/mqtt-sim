# Pro Mosquitto (Cedalo) für den ENTC-63-Harness

**Stand:** 2026-10-12 · **Bezug:** ENTC-59 (Broker-Vergleich), ENTC-63 (Abnahme)

Cedalo ist das Unternehmen hinter Eclipse Mosquitto. Pro Mosquitto, Teil der „Cedalo MQTT Platform“,
ist die kommerzielle Ausgabe: derselbe Broker plus Erweiterungen für den Produktivbetrieb. Im Lab läuft
Pro Mosquitto als zusätzlicher Compose-Service mit derselben Lab-CA, denselben Zertifikaten und derselben
generierten ACL wie der Lab-Mosquitto:

```bash
docker login registry.cedalo.com            # Zugangsdaten aus der Cedalo-Testanmeldung
cp ~/Downloads/license.lic brokers/cedalo/license/license.lic
make clean && make acceptance BROKER=cedalo  # make clean: Broker-Zertifikat braucht den Namen "cedalo"
```

**Es gibt noch keinen Lauf.** Alles unten zu Funktionen von Pro Mosquitto sind Herstellerangaben, keine
Lab-Ergebnisse. Die Baukasten-Webseite zeigt Cedalo deshalb überall als „nicht gemessen“.

## Was vor dem ersten Lauf offen ist

| Punkt | Stand | Was tun |
|---|---|---|
| Image-Tag | `registry.cedalo.com/mosquitto/mosquitto:2.9` ist der neueste Tag in Cedalos Beispielen (Blog, älter); die Plattform steht laut Release-Blog bei 3.2 | Tag im Cedalo-Konto nachsehen, dann `CEDALO_IMAGE=registry.cedalo.com/mosquitto/mosquitto:<tag> make acceptance BROKER=cedalo` |
| Lizenz | Cedalos Compose-Beispiele übergeben die Datei über `CEDALO_LICENSE_FILE`; die Testlizenz heißt dort `license.lic` | Datei nach `brokers/cedalo/license/license.lic` (wird nicht eingecheckt). Heißt die Variable inzwischen anders: in `docker-compose.yml` anpassen |
| Log-Muster, Startmeldung | vom Open-Source-Mosquitto übernommen | Nach dem ersten Lauf bestätigen, dann `status = "verified"` in `sim/targets/cedalo.toml` |
| Pro-Plugins | nicht eingeschaltet (Pfade und Optionen ungeprüft) | Siehe „Nächste Schritte“ |

## Dateien

| Datei | Zweck |
|---|---|
| `mosquitto.conf` | Konfiguration im Container: mTLS wie im Lab, `use_identity_as_username`, generierte `acl_file`, dazu **`crlfile`** (der Lab-Mosquitto hat keine CRL) |
| `license/` | Ablage für die Lizenzdatei, von Git ignoriert |
| `../../sim/targets/cedalo.toml` | Harness-Profil: Service `cedalo`, `localhost:8885` bzw. `cedalo:8883`, Hooks über SIGHUP, Aufwand je Anforderung (alle `TBD`) |
| `../../mosquitto/config/acl` | dieselbe ACL wie beim Lab-Mosquitto (`make fleet`), nur gelesen |

## Erwartung vor dem ersten Lauf

Einschätzung aus dem Open-Source-Lauf (`docs/mqtt-tests/reference/2026-10-08-mosquitto-2.0.18-v13.md`)
und den Herstellerangaben. Der Lauf liefert die Belege.

| Fall | Erwartung | Begründung |
|---|---|---|
| MTLS-01…07, ACL-01…07, ACL-13 | PASS | gleiche Mechanik wie Open-Source-Mosquitto |
| MTLS-08 | eher PASS | `crlfile` ist hier gesetzt (beim Lab-Mosquitto nicht) |
| ACL-08…12 | PARTIAL wie bei Mosquitto, falls Pro verweigerte SUBSCRIBE weiter mit SUBACK 1 bestätigt | Open-Source-Verhalten; keine Pro-Angabe gefunden |
| ID-01, ID-03, DUP-01, LEG-01 | FAIL wie bei Mosquitto | Keine Pro-Funktion gefunden, die Client-ID an das Zertifikat bindet, Takeover verhindert oder Zertifikate ohne CN zuordnet |
| RST-01 | eher PASS | Open-Source-Mosquitto 2.0.18 und 2.1.2 bestehen mit `persistence true` (Läufe 13.10.); Pro bewirbt zusätzlich Persistent Queueing auf Platte |
| REV-01 | eher PARTIAL | `crlfile` sperrt neue Verbindungen; ob SIGHUP offene trennt, ist offen. Cedalo nennt dafür das Trennen im Management Center |
| ACL-14 | PASS | SIGHUP wirkte beim Open-Source-Mosquitto auf offene Verbindungen |

## Herstellerangaben (recherchiert am 2026-10-12)

Belegstufe: **Herstellerangabe**. Gefunden über die Websuche; die Seiten selbst waren aus der
Lab-Umgebung nicht abrufbar (Netzwerkrichtlinie). Vor einer Entscheidung auf docs.cedalo.com prüfen.

### Unternehmen und Produkt

| Angabe | Quelle |
|---|---|
| Cedalo, gegründet 2017, Sitz Freiburg; Büros in Freiburg, München, Bonn; „200+ Enterprise Customers“ | [cedalo.com/company](https://www.cedalo.com/company), [LinkedIn](https://www.linkedin.com/company/cedalo-gmbh) |
| Pflegt Eclipse Mosquitto; Pro Mosquitto ist geschlossene, kommerzielle Software mit Testversion | [Broker-Seite](https://www.cedalo.com/pro-mosquitto/broker), [Integrationen](https://cedalo.com/mqtt-broker-pro-mosquitto/mqtt-integrations/) |
| Cedalo MQTT Platform 3.2 (Blog vom 02.06.2026): High Performance Clustering (aktiv/aktiv), Log-Streaming in der Oberfläche, Pub/Sub-Ratenbegrenzung, Databricks-Bridge, Sparkplug-Decode | [Release 3.2](https://www.cedalo.com/blog/cedalo-mqtt-platform-release-3-2) |
| Vergleichsseite (Stand Sept. 2026, Plattform 3.2): „77 Funktionen“ über Open-Source-Mosquitto hinaus; Sicherheits-Patches erreichen Pro-Kunden laut Broker-Seite Wochen bis Monate vor dem Open-Source-Release | [Vergleich](https://www.cedalo.com/mqtt-broker-comparison), [Broker-Seite](https://www.cedalo.com/pro-mosquitto/broker) |
| Eclipse Mosquitto 2.1 (Jan./Feb. 2026): `acl_file` und `password_file` werden Plugins (Optionen bleiben bis 3.0), TLS 1.1 entfernt, Persistenz über SQLite-Plugin | [Cedalo-Blog zu 2.1](https://www.cedalo.com/blog/introducing-eclipse-mosquitto-2-1), [mosquitto.org 2.1.0](https://mosquitto.org/blog/2026/01/version-2-1-0-released/) |

### Bezug zu den ENETEC-Anforderungen

| Anforderung | Herstellerangabe | Im Lab |
|---|---|---|
| R01–R04 mTLS, CA, Widerruf | mTLS wie Open Source (`require_certificate`, `cafile`, `crlfile`); Pro: Zertifikatsverwaltung mit eigenen CAs, „Import, deploy, and revoke CAs and client certificates“ im Management Center; Management Center kann sich seit Pro Mosquitto 2.5 selbst per Client-Zertifikat verbinden | offen |
| R05, R07–R10 Rechte | Dynamic Security (Rollen, Gruppen, ACLs) und RBAC, per Management Center und REST-API; im Lab bewusst `acl_file`. Bekanntes Open-Source-Problem bei Dynamic Security mit Zertifikats-Clients: [Issue #2999](https://github.com/eclipse-mosquitto/mosquitto/issues/2999) | offen |
| R06, R11, R16 Client-ID, Takeover, Legacy | keine Angabe gefunden | offen, Open Source: FAIL |
| R13, R22 Session, Neustart | Persistent Queueing auf Platte, übersteht Neustarts; Persistenz über SQLite-Plugin, seit Pro 2.5 auch LMDB | offen, Open Source 2.0.18 und 2.1.2 mit `persistence true`: RST-01 PASS |
| R15 Audit | Audit-Trail-Plugin (Verbindungen, Abos, ACL-Änderungen; Ausgabe auch an syslog) | offen |
| R23 Widerruf offener Sessions | Clients im Management Center trennen; ob eine neue CRL offene Verbindungen beendet, ist nicht belegt. Open-Source-Fallstricke: [Issue #2916](https://github.com/eclipse/mosquitto/issues/2916) (Fehler nach Reload mit `crlfile`) | offen |
| Betrieb, HA | HA-Cluster ab 3 Knoten: „Full Sync“ (aktiv/passiv, Leader per RAFT) und „Dynamic-Security Sync“ (aktiv/aktiv); Umschalten „in several seconds“; seit 3.2 zusätzlich High Performance Clustering (Enterprise) | [HA-Seite](https://www.cedalo.com/pro-mosquitto/high-availability), [Kubernetes-Tutorial](https://www.cedalo.com/blog/mosquitto-mqtt-on-kubernetes) |
| GCP | Native **Google-Pub/Sub-Bridge** („Bridge MQTT topics to Google Cloud Pub/Sub“), daneben Kafka und weitere Bridges | [Integrationen](https://cedalo.com/mqtt-broker-pro-mosquitto/mqtt-integrations/) |
| Monitoring | Management Center: Live-Verbindungen, Clients trennen, Dashboards; REST-API für Clients, ACLs, Bridges, Zertifikate, Cluster | [Management Center](https://www.cedalo.com/pro-mosquitto/management-center) |

### Kosten und Test

| Angabe | Quelle |
|---|---|
| Test: 14 Tage Cloud oder 30 Tage On-Premises, ohne Vertriebsgespräch; On-Premises als Docker-Compose-Paket mit Lizenzdatei | [Broker-Seite](https://www.cedalo.com/pro-mosquitto/broker) |
| Cloud-Preise: S 39 €/Monat (bis 30 Clients), M 89 €/Monat (bis 300 Clients), jeweils jährlich; Enterprise (3.000+ Clients, HA) auf Anfrage; zusätzlicher Verkehr 0,117 €/GB. Für ~10.000 Gateways also nur Enterprise | [Preise](https://www.cedalo.com/pricing) |
| On-Premises-Preise: nicht veröffentlicht | – |
| Free Tier: kostenlos für eine verbundene Mosquitto-Instanz (Management-Oberfläche, Dynamic-Security-Verwaltung) | [Free Tier](https://www.cedalo.com/blog/cedalo-mqtt-platform-free-tier) |
| Cloud-Hosting-Region / Datenhaltung: keine Angabe gefunden | offen |

## Nächste Schritte

1. 30-Tage-Test On-Premises anfordern, `make acceptance BROKER=cedalo` (Profil `v13`).
2. Prüfen, ob die Pro-Persistenz (SQLite/LMDB) RST-01 ebenso besteht wie `persistence true`.
3. Widerruf: prüfen, ob SIGHUP mit neuer CRL offene Verbindungen trennt (REV-01); sonst den
   Trennbefehl der REST-API als `SIM_HOOK_CRL_RELOAD` hinterlegen.
4. Bei Cedalo nachfragen: Client-ID an Zertifikat binden (R06), Takeover verhindern (R11),
   Zertifikate ohne CN per Fingerprint zuordnen (R16), Google-Pub/Sub-Bridge (Konfiguration,
   QoS, Reihenfolge), On-Premises-Preis für ~10.000 Gateways, Datenhaltung der Cloud.

## Fehlersuche

| Meldung | Ursache und Lösung |
|---|---|
| `pull access denied` / `unauthorized` | `docker login registry.cedalo.com` fehlt oder Test abgelaufen |
| Broker startet nicht, Log nennt die Lizenz | Lizenzdatei fehlt in `brokers/cedalo/license/` oder Variable heißt anders (Tabelle oben) |
| `Broker certificate has no SAN "cedalo"` | Lab älter als dieser Stand: `make clean && make acceptance BROKER=cedalo` |
| Jeder Client wird abgelehnt (auch MTLS-01) | CRL passt nicht zur CA oder ist abgelaufen: `rm -rf certs/negative` und neu starten; zur Not `crlfile` auskommentieren (dann MTLS-08/REV-01 ohne CRL) |
