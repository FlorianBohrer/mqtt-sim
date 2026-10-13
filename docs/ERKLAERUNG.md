# Interaktive Erklärung „Der MQTT-Kreislauf“

**Stand:** 2026-10-13 · **Seite:** [`web/erklaerung/index.html`](../web/erklaerung/index.html) (Deutsch und Englisch)

Die Seite erklärt die MQTT-Strecke wie eine technische Anlage: erst die Bauteile, dann folgt man einer
Nachricht vom Gateway in die Cloud und als Command zurück. Man geht zwölf Stationen durch und löst an
jeder selbst etwas aus. Gezeigt wird das **Soll** nach den ENETEC-Anforderungen R01–R15, nicht ein
bestimmter Broker. Was Mosquitto und EMQX im Lab wirklich getan haben, zeigt der Baukasten
([`web/baukasten/index.html`](../web/baukasten/index.html)).

## 1. Erzählweise

| Mittel | Auf der Seite |
|---|---|
| **Inventur zuerst** | Station 1: ein Satz zählt alle Bauteile auf, die Teile stehen freigestellt nebeneinander, jedes anklickbar |
| **Ein Satz Ziel** | Station 2: jede Nachricht kommt dort an, wo sie hindarf, nichts geht verloren, Fremdes bleibt draußen |
| **Dem Weg folgen** | Reihenfolge der Stationen = Weg einer Nachricht; jeder Satz beginnt mit einer Ortsangabe („Als Erstes“, „Danach“, „Am Ende“) |
| **Bilder nur für die wichtigen Teile** | Broker = Herz, Rechteliste = Weiche, Session-Speicher = „Abzweigung, ein Bypass“; das Fachwort steht gleich daneben |
| **Das Bild folgt der Erzählung** | Das erklärte Teil bleibt voll sichtbar, der Rest tritt zurück; die Fließweg-Leiste unter dem Bild füllt sich bis zur aktuellen Station |
| **Nur ein Etikett, wo es nötig ist** | Pfeil „Rechteliste, make fleet“ an der Weiche |
| **Den Kreis schließen** | Station 11 endet mit „Und der Kreislauf beginnt von vorn.“ |
| **Sprache** | kurze Hauptsätze, „ihr“-Ansprache, „quasi“; Bedienelemente sprechen die Leser ebenso an („Probiert es aus“) |

## 2. Bildsprache

Die Seite zeigt diese Tabelle zweisprachig unter „Was die Bilder bedeuten“ (`MAPPING` im Skript).

| Im Bild | Bei uns | Wo das Bild hinkt |
|---|---|---|
| Wasser in den Rohren | Nachrichten: `state` blau, `cmd` orange | Wasser ist ein Strom; Nachrichten sind einzelne Pakete mit Topic, QoS und eigener Bestätigung |
| Pumpe, das Herz | Broker | Eine Pumpe treibt an, der Broker vermittelt nur |
| Filter | Zertifikatsprüfung (mTLS, Lab-CA) | Die Prüfung passiert einmal pro Verbindung, nicht pro Tropfen |
| Weiche | Rechteliste (ACL) aus `make fleet` | Die Rechteliste entscheidet je Gateway, Richtung und Topic |
| Abzweigung, Bypass | Session-Speicher je Gateway | Die Session bekommt nur Commands für Gateways, die gerade fehlen |
| Messstation | Audit-Log, im Lab dazu der Harness | Das Log greift nicht ein und speichert keine Inhalte |
| Kreislauf | `state` hin, Command zurück | Am Cloud-Ingest verlässt die Nachricht die Anlage, das Command ist eine neue Nachricht |

## 3. Das Soll-Modell

Was die Seite bei einer Aktion zeigt, folgt MQTT 5 und den Anforderungen aus
[`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md). Ausgangslage: alle vier
Lab-Gateways verbunden, persistente Session, eigenes `cmd` abonniert.

| Aktion | Soll | Anforderung |
|---|---|---|
| Verbinden ohne Zertifikat / fremde CA / abgelaufen / widerrufen | TLS-Handshake bricht ab, es kommt nie ein CONNECT an, also auch kein CONNACK. Eine bestehende Verbindung desselben Gateways läuft weiter | R02, R03, R04 |
| Zertifikat von A, Client-ID von B | CONNACK 0x85 (Client Identifier not valid), Session von B bleibt | R06 (ID-01) |
| Zweite Verbindung mit der Client-ID eines verbundenen Gateways | Zweite Verbindung abgelehnt (CONNACK ab 0x80), die bestehende arbeitet weiter. **Strenger als MQTT selbst:** der Standard lässt die neue gewinnen (DISCONNECT 0x8E an die alte) | R11 (DUP-01) |
| Reconnect mit Clean Start = false | CONNACK 0x00, `session_present = 1`, wartende Commands werden zugestellt | R13 (SES-01) |
| Reconnect mit Clean Start = true | Alte Session und wartende Commands verworfen, `session_present = 0`, neues SUBSCRIBE (SUBACK 0x01) | R13 (SES-02) |
| Netz weg | Kein DISCONNECT; der Broker trennt erst nach 1,5 × Keep Alive (120 s → 3 min). Session bleibt | R13 |
| PUBLISH in eigenes `state` | Erlaubt, PUBACK 0x00. PUBACK heißt nur „übernommen“; als zugestellt gilt die Nachricht erst, wenn Cloud-Ingest (`enetec/v1/+/state`) sie bekommt | R08, R12 |
| PUBLISH in eigenes `cmd` / fremdes `state` / Topic außerhalb | PUBACK 0x87 (Not authorized), nichts wird zugestellt | R08 / R10 / R07 |
| SUBSCRIBE eigenes `cmd` | SUBACK 0x01 (QoS 1 gewährt) | R09 |
| SUBSCRIBE eigenes `state` / fremdes `cmd` / `enetec/v1/#` | SUBACK 0x87. Mosquitto bestätigt im Lab mit 0x01 und liefert nur nichts aus (PARTIAL) | R09 / R10 |
| Command an verbundenes Gateway | Zustellung an genau dieses Gateway, PUBACK 0x00 an Cloud-Command | R09, R12 |
| Command an Offline-Gateway mit Session | Broker parkt es in der Session, PUBACK 0x00 | R13 |
| Command nach abgelaufener Session | PUBACK 0x10 (No matching subscribers): angenommen, aber niemand bekommt es | R13 |

**Audit-Log:** Normale Zeilen haben genau das Format, das Mosquitto 2.0.18 schreibt (im Referenzlauf
gesehen oder im Quelltext von 2.0.18 nachgelesen: `New client connected …`, `OpenSSL Error[0] …`,
`Denied PUBLISH …`, `Client … has exceeded timeout, disconnecting.`, `Expiring client … due to
timeout.`). Für Prüfungen, die Mosquitto nicht protokolliert (Client-ID-Registry, doppelte Client-ID,
abgelehntes SUBSCRIBE), steht eine kursive Soll-Zeile. Die Zeitstempel laufen mit einer simulierten Uhr,
die bei Keep Alive und Session Expiry vorspringt. Die IP-Adressen sind Beispielwerte.

**Werte:** Gateways, Seriennummern, Client-IDs und ACL-Zeilen stammen aus `synthetic/fleet.json` und
`mosquitto/config/acl`, Keep Alive (120 s) und Session Expiry (3600 s, Wert offen) aus
`sim/config.toml`. Die Tests prüfen das (`ExplainerTest`).

### Was gegenüber dem Erklärfilm korrigiert wurde

- Die Zertifikatsprüfung passiert einmal beim Verbindungsaufbau; danach prüft der Broker die
  Client-ID gegen das Zertifikat (R06) und die Rechteliste bei jedem PUBLISH/SUBSCRIBE.
- Der Session-Speicher liegt auf dem Command-Weg hinter der Rechteliste, nicht im Zustandsfluss.
- Das Audit-Log hängt am Broker und protokolliert Verbindungen, Ablehnungen und verweigerte Zugriffe,
  keine Nachrichteninhalte.
- PUBACK bedeutet „übernommen“, nicht „zugestellt“; Zeuge ist der Empfänger.
- Doppelte Client-ID (R11) und Keep-Alive-Erkennung bei Netzverlust sind neu dabei.
- Pro Mosquitto wird nicht als gemessen dargestellt; es gibt noch keinen Lauf.

## 4. Aufbau der Seite

| Teil | Wo |
|---|---|
| Stationen: Kapitel, Erzähltext DE/EN, Ansicht, hervorgehobene Teile | JSON-Block `<script id="stations-data">` |
| „Probiert es aus“ je Station | `tryHtml(id)` im Skript, ein `case` je Station |
| Soll-Modell und Abläufe | `connect()`, `drop()`, `publish()`, `subscribe()`, `sendCmd()`, `expire()` |
| Zeichnung der Bauteile und Rohre | `PIPES`, `ROUTE`, `gateway()`, `pump()`, `valve()` … |
| Feste Texte, Bildsprache | `UI`, `MAPPING` |
| Schriften, CSP-Hash | `make web` (wie beim Baukasten) |

Felder einer Station:

| Feld | Bedeutung |
|---|---|
| `id` | Schlüssel, auch für `tryHtml` und `data-go` an den Bauteilen |
| `view` | `lineup` (Bauteile nebeneinander) oder `plant` (die Anlage) |
| `focus` | Bauteile, die voll sichtbar bleiben (`gw1`–`gw4`, `manifold`, `filter`, `broker`, `valve`, `session`, `audit`, `ingest`, `command`); leer = alles gleich |
| `only` | Elemente, die nur an dieser Station erscheinen (`idcard`) |
| `chapter`, `text` | Titel und Erzähltext, je `de` und `en` |

**Gestaltung:** dieselbe Farbwelt wie der Baukasten (RAL 7035 Lichtgrau, Signalblau). Wasser (blau) =
`state`, Kupfer = `cmd`, gestrichelt = geplant. Eine Ablehnung erscheint als geschlossene Armatur im
Rohr, der Ablauf rechts als Mitschnitt mit Log-Stufen (OK, DENY, WARN, INFO) und Anforderung.

**Text ändern:** Erzähltext im JSON ändern (immer `de` und `en`), Seite neu laden.
**Skript ändern:** danach `make web`, sonst blockiert die CSP das Skript.
**Prüfen:** `cd sim && python3 -m unittest tests.test_webdata` (Zweisprachigkeit, Bauteil-Namen,
echte Lab-Werte, Log-Formate, CSP), dann `make web-check`: Der Browser-Test klickt jede Station und
jede Aktion in beiden Sprachen durch, prüft das Soll-Modell, Breiten von 360 bis 1440 px, CSP und
dass die Seite nichts von außen lädt.

---

## In English (summary)

The page explains the MQTT chain like a technical installation: first all parts side by side, then
you follow one message from the gateway to the cloud and back as a command. There are twelve stations,
and at each one you trigger something yourself. The page shows the **target behaviour** per ENETEC R01–R15 with MQTT 5
reason codes, not a particular broker; the building kit shows what the brokers did in the lab.

- **Storytelling:** inventory first, one sentence for the goal, follow the path of a message, images only
  for the key parts (broker = heart, permission list = switch, session store = bypass), one label where
  needed, close the circle ("And the circuit starts all over again."). The page explains where each
  picture falls short.
- **Target model:** TLS failures never reach CONNECT (R02–R04); certificate A with client ID B gets
  CONNACK 0x85 (R06); a second connection with an active client ID is rejected while the first one
  stays, which is stricter than plain MQTT, where the new connection takes over (R11); Clean Start
  false/true and session expiry (R13); PUBACK means "taken over", the receiver is the witness (R12);
  denied PUBLISH/SUBSCRIBE get 0x87 (R07–R10); a command with no subscriber gets PUBACK 0x10.
- **Audit log:** regular lines use the exact Mosquitto 2.0.18 formats; checks Mosquitto does not log
  appear as italic target lines.
- **Values:** gateways, client IDs and ACL lines come from the committed fleet, timers from
  `sim/config.toml`; `ExplainerTest` checks this.

Stations live in the JSON block `<script id="stations-data">`; run `make web` after editing the script.
