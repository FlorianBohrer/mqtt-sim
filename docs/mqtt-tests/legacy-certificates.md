# Legacy-Zertifikate (AWS IoT) und Zertifikatsrotation

**Stand:** 2026-10-01 · **Bezug:** ENTC-31, ENTC-58, ENTC-59, ENTC-63 · **Quelle:** ENETEC-Mitteilung
zum Test-Gateway `0000000000000005` inklusive des öffentlichen Client-Zertifikats

## 1. Analyse des echten Zertifikats (SOURCE)

Untersucht wurde nur das öffentliche Zertifikat. Es ist nicht im Repo, und es liegt kein Schlüssel vor.

| Merkmal | Befund |
|---|---|
| Subject | `C=UK, ST=United`: **kein CN, keine SAN, keine Gateway-ID** |
| Issuer | `OU=Amazon Web Services O=Amazon.com Inc. L=Seattle ST=Washington C=US` (AWS-IoT-interne CA) |
| Schlüssel / Signatur | RSA 2048 / sha256WithRSAEncryption |
| Gültigkeit | 2020-02-27 bis **2049-12-31** |
| Key Usage / EKU | `digitalSignature` (critical) / keine EKU |
| Mitgeliefertes „rootCA“ | VeriSign Class 3 Public Primary CA G5. Das ist der Trust-Anker des Gateways für den **AWS-Server**, nicht der Aussteller des Client-Zertifikats. |

**Bisheriger Ablauf laut ENETEC:**
1. Die Provisioning-Workstation erzeugt RSA-2048-Schlüssel und CSR.
2. AWS IoT Fleet Provisioning (Claim) signiert die CSR und registriert das Thing.
3. Zertifikat, Schlüssel, CA und Konfiguration werden in der Produktion installiert.

Legacy-Gateways (Debian Jessie/Buster) können Schlüssel und CSR auch lokal erzeugen. Für die
„new generation“-Geräte ist das noch zu bestätigen.

## 2. Konsequenzen

1. **Die Identität steckt nicht im Zertifikat.** AWS ordnet das Zertifikat über die Registry
   (Zertifikat → Thing) zu. Ein Broker, der die Identität aus CN/SAN liest, kann ein solches
   Gateway nicht zuordnen. Zwei Legacy-Zertifikate haben zudem **denselben Subject**. Es gibt
   zwei Optionen (OPEN, ENTC-31/58):
   - **(a) Registry-Lookup:** Fingerprint oder Seriennummer des Zertifikats → Gateway-ID, als Broker-Plugin oder externer Auth-Service.
   - **(b) Neuausstellung:** Gateway-ID in CN/SAN, CSR-basiert über die eigene PKI.
2. **Fremd-Broker können die Kette voraussichtlich nicht prüfen.** Der Aussteller ist eine
   AWS-interne CA. Dass AWS deren Zertifikat nicht bereitstellt, ist meine Annahme und mit
   ENETEC oder AWS zu bestätigen. Trifft sie zu, ist eine Neuausstellung über die eigene PKI
   Voraussetzung für EMQX, HiveMQ oder Bevywise, also keine Option.
3. **Der Server-Trust muss ebenfalls migriert werden** (VeriSign G5 → CA des neuen Brokers).
   Das passt zur geplanten CA-Übergangsphase von ENETEC.
4. **Laufzeiten bis 2049** machen einen funktionierenden Widerruf zwingend (MTLS-08).
5. **Konflikt zwischen Rotation und doppelter Client-ID:** Da Client-ID = Gateway-ID gilt und eine
   zweite Verbindung abgelehnt wird (DUP-01), kann das Gateway die neue Identität nicht
   parallel zur alten prüfen. Der Wechsel muss deshalb lauten: alte Verbindung trennen → mit
   dem neuen Zertifikat verbinden → bei Fehler auf das alte zurückfallen. Bis zum Widerruf
   muss der Broker zwei gültige Zertifikate pro Gateway akzeptieren.

## 3. Nachbildung im Lab (`make legacy-certs`, Teil von `make acceptance`)

| Was | Wie | Ablage |
|---|---|---|
| Legacy-Gateways | `0000000000000005`, `0000000000000006` (16-stellige IDs wie im echten Feld), Plant `plt_sim_legacy` | `sim/config.toml` `[legacy]`, `synthetic/fleet.json` → `legacy_gateways` |
| Legacy-Zertifikate | Schlüssel und CSR wie auf dem Gerät: RSA 2048, SHA-256, Subject `/C=UK/ST=United`, Key Usage `digitalSignature`, keine EKU. Signiert von der **Lab-CA**, die AWS-CA wird nicht nachgebildet | `certs/legacy/<id>/` |
| Registry | SHA-256-Fingerprint → Gateway-ID, also das, was ein Broker für Option (a) bräuchte | `certs/legacy/registry.tsv` |
| Rotation | zweites, CSR-basiertes Zertifikat (RSA 2048, CN = Gateway-ID) für `gw-sim-000001` | `certs/rotation/gw-sim-000001/` |
| ACL | Blöcke für die Legacy-IDs. Sie greifen nur, wenn der Broker das Zertifikat auf die ID abbildet | `mosquitto/config/acl` |

Die Legacy-Gateways sind nicht Teil des Simulations-Datensatzes.

## 4. Acceptance-Fälle (advisory, bis ENTC-31 entschieden ist)

| Fall | Anforderung | Erwartung | Mosquitto 2.0.18 (Lab) |
|---|---|---|---|
| LEG-01 | R16 | Legacy-Zertifikat verbindet sich als sein Gateway und publiziert ins eigene d2c | **FAIL**: CONNACK 134 „Bad User Name or Password“ (kein CN → keine Identität) |
| LEG-02 | R16 | Zertifikat von Gateway 2 (gleicher Subject) kann nicht als Gateway 1 handeln | PASS, allerdings nur, weil schon die Verbindung abgelehnt wird |
| ROT-01 | R17 | altes und neues Zertifikat desselben Gateways werden beide akzeptiert | PASS |
| ROT-02 | R17 | Wechsel alt → neu; defekte neue Identität wird abgelehnt, Rückfall auf alt funktioniert | PASS |

Der Widerruf des alten Zertifikats nach der Rotation entspricht MTLS-08 (CRL/OCSP/Registry).
Beim Lab-Broker funktioniert er nur mit `crlfile`. Der Widerruf während einer bestehenden
Verbindung ist noch nicht getestet.

## 5. Offene Fragen an ENETEC

1. Kann AWS die ausstellende CA der Legacy-Zertifikate bereitstellen, oder ist die Neuausstellung
   über die eigene PKI vor der Broker-Migration Pflicht?
2. Bevorzugt ENETEC die Registry-Zuordnung (Fingerprint → Gateway-ID) für eine Übergangszeit,
   oder sofort die Gateway-ID in CN/SAN?
3. Können die „new generation“-Geräte Schlüssel und CSR lokal erzeugen? Wenn ja: mit welchem
   Schlüsseltyp (RSA 2048 oder EC P-256)?
4. Wie sieht der Aktivierungsablauf aus? Der hier geprüfte Vorschlag ist „trennen → neu verbinden →
   Rückfall“, weil zwei Verbindungen mit derselben Client-ID abgelehnt werden.
