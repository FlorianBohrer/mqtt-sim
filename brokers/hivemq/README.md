# HiveMQ CE + ENETEC-Identity-Erweiterung für den ENTC-63-Harness

**Stand:** 2026-10-08 · **Bezug:** ENTC-59 (Broker-Vergleich), ENTC-63 (Abnahme), ENTC-31 (Legacy-Identität)

```bash
make clean && make acceptance BROKER=hivemq
```

Beim ersten Lauf werden zwei Images gebaut: die Erweiterung per Maven und das HiveMQ-CE-Image
(`enetec-hivemq:local`). Danach erzeugt der Lauf den Keystore und startet den Container auf
Port **8885**. Bei jedem Lauf wird der Container neu erstellt, damit Zertifikate, Registry und
CRL des Laufs geladen sind.

## Warum eine eigene Erweiterung?

HiveMQ CE bringt außer „allow all“ keine Autorisierung mit. Die ENETEC-Anforderungen hätten dort
also keinen Ansatzpunkt. Die Lab-Erweiterung `extension/` (Open Source, etwa 300 Zeilen Java,
HiveMQ Extension SDK 4.28) setzt sie um. Jede Entscheidung loggt sie mit dem Präfix `ENETEC-AUDIT`.

| Anforderung | Umsetzung in der Erweiterung |
|---|---|
| Identität aus dem Zertifikat | CN des Client-Zertifikats, sonst Gateway-ID aus `certs/legacy/registry.tsv` (SHA-256-Fingerprint) für Legacy-Zertifikate ohne CN |
| Erlaubte Client-ID | CONNECT nur mit der Client-ID, die `client_ids.tsv` der Identität zuordnet (v13: abgeleitetes Pseudonym; fehlt die Identität dort: Client-ID = Identität), sonst CONNACK 0x85 (`ENETEC_ENFORCE_CLIENT_ID`) |
| Doppelte Client-ID | ist die Client-ID schon verbunden → CONNACK 0x85, die bestehende Session bleibt (`ENETEC_REJECT_DUPLICATE_CLIENT_ID`) |
| Widerruf | Seriennummern aus `certs/negative/crl.pem` → CONNACK 0x87 |
| Deny-by-default | Publish/Subscribe nur laut `permissions.tsv` (bei `make fleet` aus der Flotte erzeugt), sonst PUBACK/SUBACK 0x87 |
| Änderungen zur Laufzeit | alle 2 s prüft die Erweiterung CRL, `permissions.tsv`, `client_ids.tsv` und Registry; nach einer Änderung lädt sie neu, trennt offene Sessions mit widerrufenem Zertifikat und entfernt nicht mehr erlaubte Abos (REV-01, ACL-14) |
| Audit | `connect-accepted`, `connect-rejected` (mit Grund und Zertifikats-Seriennummer), `publish-denied`, `subscribe-denied`, `disconnect`, `policy-reloaded`, `session-terminated`, `subscription-removed` |

mTLS selbst (Client-Zertifikat Pflicht, Lab-CA als Truststore, TLS 1.2/1.3) ist HiveMQ-Standard
und steht in `config.xml`.

## Ergebnis (lokal: HiveMQ CE 2026.5, Java 21)

**2026-10-08, Wire-Profil v13:** ACCEPTED, 34/34 Pflichtfälle PASS, dazu RST-01 (Session übersteht
Neustart), REV-01 (Widerruf trennt die offene Session) und ACL-14 (Entzug wirkt auf die offene
Session) PASS. Bericht: [`2026-10-08-hivemq-ce-2026.5-v13.md`](../../docs/mqtt-tests/reference/2026-10-08-hivemq-ce-2026.5-v13.md).
Im Profil `lab-eicp` 33/33 (ID-03 N/A). Laut Current State 08.10 wird HiveMQ nicht mehr aktiv
verfolgt; das Ergebnis zeigt den Aufwand einer Erweiterung, keine Produktabnahme.

**2026-10-01, Profil lab-eicp:** ACCEPTED, Exit 0: 31/31 Pflichtfälle PASS. Bericht:
[`docs/mqtt-tests/reference/2026-10-01-hivemq-ce-2026.5.md`](../../docs/mqtt-tests/reference/2026-10-01-hivemq-ce-2026.5.md).
Auch die Advisory-Fälle sind PASS: MTLS-07/08, LEG-01/02 (Legacy-Zertifikat über die Registry) und ROT-01/02.

Bestätigt in zwei Umgebungen mit identischem Ergebnis (31/31 PASS, inklusive aller Advisory-Fälle):
lokal mit der HiveMQ-Distribution und am 2026-10-01 im Docker-Lab auf einem MacBook
(`make acceptance BROKER=hivemq`: Maven-Build der Erweiterung, Image `enetec-hivemq:local`,
Keystore, Start, Abnahme).

**Beobachtungen:**
- **TLS-Ablehnungen fehlen im Log.** HiveMQ CE protokolliert abgelaufene oder fremde Zertifikate
  im Standard-Loglevel nicht; LOG-02 besteht nur über die Audit-Zeilen der Erweiterung.
  Für ein vollständiges Audit wäre ein höheres Loglevel für den TLS-Handler nötig.
- **Trennung nach unberechtigtem PUBLISH.** HiveMQ sendet PUBACK 0x87 und trennt den Client
  danach (DISCONNECT „NOT_AUTHORIZED“). Das ist sicher, eine fehlerhafte Firmware kann damit
  aber in Reconnect-Schleifen geraten.
- **Zielkonflikt bei doppelter Client-ID.** Die ENETEC-Regel „neue Verbindung ablehnen“ hat
  eine Kehrseite: Nach einem stillen Verbindungsabbruch (ohne TCP-FIN) hält der Broker die alte
  Verbindung bis zum Keep-alive-Timeout (bei 120 s bis zu 180 s) für aktiv. So lange werden
  Reconnects des Gateways abgelehnt. In den Tests (Abbruch per TCP-Close) tritt das nicht auf.
  Der Punkt gehört in ENTC-58.

## Für den Produktivbetrieb (nicht Teil des Labs)

- Die Erweiterung ist ein Labor-Nachweis. In Produktion käme die Identitäts- und Rechteprüfung
  aus der Backend-Registry (Gateway ↔ Plant, Lebenszyklus) statt aus Dateien. Alternativ:
  HiveMQ Enterprise Security Extension (kommerziell).
- Das Neuladen von Registry, CRL und Rechten erfordert hier einen Neustart. Produktiv braucht es
  ein Nachladen zur Laufzeit und das Trennen aktiver Verbindungen beim Widerruf.
