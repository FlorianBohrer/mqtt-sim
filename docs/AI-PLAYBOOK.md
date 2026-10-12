# AI-Playbook: mqtt-sim (ENETEC MQTT-Lab)

**Stand:** 2026-10-12 · **Gilt für:** Claude Code und andere KI-Assistenten, die in diesem Repo arbeiten · **Kurzfassung:** [`../CLAUDE.md`](../CLAUDE.md)

Dieses Playbook legt fest, wie eine KI in diesem Projekt arbeitet: was sie selbst entscheiden darf,
woher Fakten kommen dürfen, wie typische Aufgaben ablaufen und was vor jedem Commit geprüft wird.
Es ist für Menschen genauso lesbar: Wer eine Aufgabe an eine KI gibt, findet unten fertige Auftragstexte.

---

## 1. Worum es im Repo geht

Ein Labor für die MQTT-Kommunikation **Gateway ↔ Broker** im ENETEC-Umzug von AWS IoT Core nach Google Cloud:

| Teil | Zweck | Einstieg |
|---|---|---|
| Acceptance-Harness (ENTC-63) | prüft einen Broker gegen 24 Anforderungen, Exit 0 nur wenn alle Pflichtfälle bestehen | `make acceptance [BROKER=…]` |
| Synthetische Flotte und Simulation | 24 h realistischer Verkehr mit Ausfällen und Reconnect-Sturm | `make fleet`, `make simulate` |
| Broker-Vergleich und Entscheidungsmatrix (ENTC-59) | Fakten nebeneinander, gewichtete Matrix ohne erfundene Werte | `make compare`, `make decide` |
| Baukasten-Webseite | Simulation interaktiv zusammenstecken und verstehen; Export in die echte Simulation | `web/baukasten/index.html`, `make web` |
| Dokumentation | Anleitung, Regeln, Referenzberichte, Stand | `docs/` |

## 2. Rollen

- **Mensch (Florian / SOLHEA / ENETEC)** entscheidet: Broker-Auswahl, Gewichte der Matrix, alles, was in
  den Projektunterlagen als OFFEN steht (Client-ID-Algorithmus, Paketgrenze, Widerrufsstrategie,
  Session-Werte, Regel bei doppelter Client-ID), Merge nach `main`.
- **KI** baut, misst, dokumentiert und schlägt vor. Sie markiert Offenes als OFFEN, statt es zu entscheiden,
  und fragt nach, wenn eine Aufgabe eine dieser Entscheidungen voraussetzt.

## 3. Grundregeln (nicht verhandelbar)

1. **Quellenhierarchie.** Nachrichten-Semantik kommt aus ENTC-61 / MQTT wire contract v1.3. Danach
   bestätigte Entscheidungen aus Jira (ENTC-47/58/59/63) und der jeweils neueste „ENETEC MQTT Current State“.
   Frühere Lab-Berichte sind historische Evidenz, keine Spezifikation.
2. **Nichts erfinden.** Keine Message-Codes, Payload-Felder, Grenzwerte oder Algorithmen ausdenken.
   Wo etwas fehlt: als Platzhalter kennzeichnen (Beispiel: `lab-sha256-v0` für die Client-ID-Ableitung).
3. **Kennzeichnung** in Konfiguration und Doku: `SOURCE` (mit Quelle), `INTERPRETED`, `ASSUMPTION`, `OPEN`.
4. **Broker-Verhalten nur aus Lab-Läufen.** Ein Ergebnis gilt erst, wenn ein Lauf es zeigt. Die Webseite und
   die Matrix lesen Ergebnisse ausschließlich aus Dateien in `docs/mqtt-tests/reference/`. Kein Ergebnis
   von Hand eintragen, auch nicht „vorläufig“.
5. **Messprinzipien des Harness bleiben.**
   - Zustellung wird an einem berechtigten Zeugen gemessen, nicht am PUBACK.
   - Ohne Positivkontrolle (MTLS-01) zählt keine Ablehnung.
   - Nicht erreichbar heißt nie „abgelehnt“.
   - INCONCLUSIVE ist nie PASS.
   - Ein gefilterter Lauf (`--only`) ist nie eine Abnahme.
6. **Payloads sind opak.** Der Harness dekodiert keine Anwendungsdaten. Das JSON der Simulation ist ein
   synthetisches Fixture, nicht das v1.3-Binärformat.
7. **Keine Geheimnisse.** Keine echten Zertifikate, Schlüssel, Passwörter oder Kundendaten committen.
   `certs/`, `results/`, `data/`, `sim/config.local.toml` und das Bevywise-Bundle bleiben lokal (`.gitignore`).
8. **Generierte Dateien nie von Hand ändern.** Dazu gehören:
   - `synthetic/`
   - `mosquitto/config/acl`, `brokers/emqx/acl.conf`, `brokers/hivemq/*.tsv`
   - `brokers/bevywise/generated/`
   - der Datenblock in `web/baukasten/index.html`

   Stattdessen den Generator ändern und neu erzeugen. Die Tests prüfen, dass die Dateien aktuell sind.
9. **Abwärtskompatibel bleiben.** `WIRE=lab-eicp` muss das frühere Schema byte-identisch reproduzieren.
   Neue optionale Felder dürfen bestehende Ausgaben nicht ändern; der Test
   `test_committed_files_are_reproducible` zeigt es.
10. **Ehrlich berichten.** Was nicht getestet wurde (z. B. ohne Docker), steht ausdrücklich im Bericht
    und in der Antwort.

## 4. Projektkarte

| Pfad | Inhalt | Wer ändert |
|---|---|---|
| `sim/config.toml` | Flotte, Verkehr, Wire-Profil, Annahmen | KI nach Auftrag, Kennzeichnung pflegen |
| `sim/config.local.toml` | lokale Ergänzung, z. B. Export aus dem Baukasten | Nutzer, nicht committen |
| `sim/enetec_sim/wire.py` | Topic-Schema v13 / lab-eicp, Client-ID-Ableitung | nur bei Spec-Änderung |
| `sim/enetec_sim/acceptance.py` | Testfälle, Anforderungen R01–R24, Befunde, Bericht | Rezept B |
| `sim/enetec_sim/fleet.py`, `dataset.py`, `simulate.py`, `verify.py` | Flotte, Verkehr, Simulation, Auswertung | |
| `sim/enetec_sim/compare.py`, `decide.py` | Vergleich, Entscheidungsmatrix | |
| `sim/enetec_sim/webdata.py` | Daten für die Webseite | Rezept C/D |
| `sim/targets/*.toml` | Broker-Profile (Adresse, Log-Muster, Hooks, Aufwand) | Rezept A |
| `sim/decision.toml` | Gewichte, Kandidaten, belegte Handbewertungen | Gewichte nur auf Ansage |
| `scripts/13_acceptance.sh` | Abnahme inkl. Hook-Runner | |
| `brokers/<broker>/` | Broker-Konfiguration und Anleitung | Rezept A |
| `web/baukasten/index.html` | Webseite (eine Datei, ohne Build) | Rezept D |
| `web/baukasten/sources.toml` | welche Referenzläufe die Seite zeigt, Broker-Texte DE/EN | Rezept C |
| `web/baukasten/fonts/` | eingebettete Schriften (SIL OFL 1.1) | nur mit Lizenzdatei |
| `docs/mqtt-tests/reference/` | Referenzberichte (Evidenz) | nur echte Läufe |
| `docs/MQTT-SIM-ENV.md` / `.en.md` | Anleitung DE / EN | bei jeder Nutzer-sichtbaren Änderung |
| `docs/STAND-*.md` | Statusberichte | Rezept F |

## 5. Rezepte

### A. Neuen Broker anbinden

1. Profil kopieren: `sim/targets/emqx.toml` → `sim/targets/<name>.toml`.
2. Eintragen:
   - `name`, `status = "template"`, `host`, `port`
   - die Log-Muster unter `[log]`
   - `[hooks]`, falls bekannt, wie der Broker CRL und ACL nachlädt
3. Unter `brokers/<name>/README.md` beschreiben, wie der Broker aus `synthetic/fleet.json` konfiguriert wird:
   - CA vertrauen, CN als Identität, erlaubte Client-ID
   - je Gateway nur eigenes `state` schreiben und eigenes `cmd` lesen
   - Konfigurationsschlüssel nur aus der Herstellerdoku, mit Link; Unbekanntes als `[OFFEN]`
4. Lauf: `make acceptance BROKER=<name>` (bei externem Broker `SIM_BROKER_HOST`, `SIM_BROKER_LOG`, `SIM_HOOK_*`).
5. Log-Muster aus dem echten Log nachziehen; erst dann `status = "verified"`.
6. Aufwandsklassen `[effort]` nur aus beobachteten Ergebnissen.
7. Den Bericht als Referenz ablegen (Rezept C) und den Kandidaten in `sim/decision.toml` eintragen.

### B. Neuen Testfall hinzufügen

1. In `sim/enetec_sim/acceptance.py` mit `@case(...)` anlegen:
   - Pflicht nur, wenn die Anforderung bestätigt ist; sonst `mandatory=False`
   - `applies=` setzen, wenn der Fall nur für ein Wire-Profil gilt
   - Messung über einen Zeugen, Positivkontrolle beachten
   - keine Wartezeiten raten; `observe_s` nutzen
2. Neue Anforderung in `REQUIREMENTS`; den Befund für FAIL/PARTIAL in `FINDINGS`, broker-neutral formuliert.
3. Braucht der Fall eine Aktion am Broker während des Laufs: Hook über `hook(h, '<name>')`, den
   Gegenpart in `scripts/13_acceptance.sh` und den Integrationstest (`HookRunner`).
4. Tests:
   - `sim/tests/test_acceptance_report.py` (Exit-Semantik)
   - Integrationstest gegen lokalen Mosquitto, falls möglich
5. Doku nachziehen:
   - `docs/mqtt-tests/acceptance-harness.md` (Tabelle Anforderungen/Fälle)
   - beide Anleitungen
6. Webseite: deutschen Text in `CASE_DE` ergänzen (Titel, `kind`, `why`), dazu eine Aktion in `ACTIONS`;
   sonst zeigt die Seite den Fall nur im Vergleich.

### C. Neuer Referenzlauf

1. Lauf ausführen. `report.md` aus `results/acceptance-<lauf>/` nach
   `docs/mqtt-tests/reference/<datum>-<broker>-<version>-<wire>.md` kopieren.
   - Fehlt der Bericht und gibt es nur die Zusammenfassung: wortgetreu als `.txt` mit Kopfkommentar zur Herkunft.
2. In `web/baukasten/sources.toml` einen `[[run]]`-Eintrag ergänzen (`kind = "report"` oder `"summary"` mit `cases`).
3. Daten neu erzeugen: `make web`, lokal `SIM_LOCAL=1 make web`.
4. Prüfen: `test_committed_page_carries_current_data` muss grün sein.
5. Ändert sich ein Kernergebnis: `docs/STAND-*.md` und die Ergebnisabschnitte der Anleitungen aktualisieren.

### D. Baukasten-Webseite erweitern

Die Seite ist **eine** HTML-Datei ohne Build-Schritt. Sie läuft per `file://` und als veröffentlichte Seite,
auf Deutsch und Englisch (Umschalter oben rechts, `?lang=en`, sonst Browsersprache).

`make web` schreibt drei Dinge in die Datei: die Lab-Daten (`DATA`), die Schriften aus
`web/baukasten/fonts/` als `data:`-URIs und den SHA-256 des Seitenskripts in die
Content-Security-Policy. **Nach jeder Änderung am Skript `make web` ausführen**, sonst blockiert der
Browser das Skript (die Seite bleibt leer) und `test_csp_allows_only_the_page_script` schlägt fehl.

**Aufbau im Skript:**

| Teil | Inhalt |
|---|---|
| `DATA` | Daten aus `make web`, nicht von Hand |
| `CASE_DE` / `CASE_EN` | Testfall → Titel, Ablauftyp (`kind`, nur DE), Begründung (`why`) |
| `REQ_DE` / `REQ_EN`, `GLOSSARY` / `GLOSSARY_EN`, `UI` | Anforderungen, Glossar, feste HTML-Texte (`data-i18n`) |
| `L(de, en)` | wählt den Text der aktuellen Sprache; jeder neue Text braucht beide Fassungen |
| `cleanState()` | prüft den gespeicherten Zustand aus `localStorage` (Whitelist) |
| `ACTIONS` | Knöpfe am Gateway/Broker → Testfall(e) |
| `buildFlow()` | Ablaufschritte je `kind` und Ergebnis (PASS/FAIL/PARTIAL/nicht gemessen) |
| `LESSONS` | Lernpfad |
| `exportToml()` | Export nach `sim/config.local.toml` (reine Funktion) |
| `configText()` | ACL-Vorschau; muss dieselben Regeln wie `sim/enetec_sim/fleet.py` nutzen |

**Regeln:**
- Ergebnis-Farbe und Text kommen immer aus `resultFor(caseId)`. Gibt es keinen Lauf, steht dort „nicht gemessen“.
- Die abgeleitete Client-ID muss mit Python übereinstimmen (`deriveClientId` ↔ `wire.derive_client_id`).
- Farben nur über die CSS-Tokens in `:root`, Hell- und Dunkelmodus pflegen.
- Texte kurz, aus Sicht der Nutzer, immer **deutsch und englisch** (`L("…", "…")`, Tabellen `*_EN`,
  in `sources.toml` die Felder `*_en`). `BilingualTest` prüft Testfälle, Anforderungen und Quellen.

**Sicherheitsregeln (nicht verhandelbar):**
- Kein Nachladen von Dritten: keine CDNs, keine Webfonts, kein `fetch`. Die CSP (`default-src 'none'`)
  verbietet es ohnehin; `PageSecurityTest` prüft es.
- Kein zweites Inline-Skript, keine `on…=`-Attribute, kein `eval`/`new Function`. Ereignisse nur über
  die zentralen `addEventListener`-Handler.
- Alles, was in HTML eingesetzt wird, läuft durch `esc()`. Werte in `class`-Attributen nur über
  `VCLASS()`/`SCLASS()`/`TONE()` (feste Listen), nie roh.
- `data-*`-Werte aus dem DOM und Formularwerte vor Gebrauch gegen feste Listen prüfen
  (`Object.hasOwn(ACTIONS, …)`, `TABS`, `SELECTABLE`, `CERTS` …).
- Neues Feld im Zustand → auch in `cleanState()` prüfen; sonst wird es beim Laden verworfen.
- Export (`exportToml`) nur aus geprüften Werten; Zeichenketten über `tomlValue()` (JSON-Quoting).

**Prüfen nach jeder Änderung:**
1. `make web`, dann `node --check` auf das extrahierte Skript.
2. Einmal im Browser, **in beiden Sprachen**: Lab-Flotte laden, jede Aktion auslösen, keine Fehler und
   keine CSP-Meldungen in der Konsole, kein seitliches Scrollen bei 360 und 390 px Breite.
3. Hat sich `exportToml` geändert:
   - Export für einen selbst gebauten Aufbau erzeugen und mit
     `SIM_CONFIG_OVERLAY=<datei> python -m enetec_sim generate --no-acl --out <tmp>` gegenprüfen;
     Gateways, Installationen, Seriennummern, Client-IDs und Anbindungen müssen gleich sein.
   - Die Fixture `sim/tests/fixtures/baukasten-export*.{toml,json}` erneuern, wenn sich das Format ändert.

### E. Spezifikation ändert sich (z. B. ENTC-47 Client-ID, ENTC-61 Paketgrenze)

1. Quelle im Auftrag nennen lassen (Dokument, Version, Datum). Ohne Quelle nichts ändern.
2. Wire-Änderungen in `sim/enetec_sim/wire.py`, neue Algorithmus-Version als neuen Wert von
   `client_id_algorithm`; den alten Wert behalten, damit frühere Läufe reproduzierbar bleiben.
3. Paketgrenze: `max_packet_bytes` im Broker-Profil; PAY-03 wird dadurch aktiv.
4. `make fleet`, Tests, Doku und `docs/STAND-*.md`; Kennzeichnung von OFFEN auf SOURCE ändern.

### F. Status- oder Jira-Bericht

1. Fakten nur aus `docs/mqtt-tests/reference/`, `make compare`, `make decide` und den Projektunterlagen.
2. Neuen `docs/STAND-<datum>.md` anlegen statt den alten zu überschreiben. Aufbau wie der vorige:
   - Kurzfassung, Ergebnisse, Befunde
   - Matrix, Grenzen, offene Entscheidungen, nächste Schritte
3. Gemessen, beraten und nicht getestet klar trennen.

## 6. Auftragsvorlagen (zum Kopieren)

> **Broker anbinden:** „Binde `<Broker, Version>` als Profil an (Rezept A im AI-Playbook). Quellen für
> die Konfiguration: `<Links>`. Markiere alles Unbelegte als OFFEN. Ich führe den Lauf aus und gebe dir
> die Ausgabe.“

> **Testfall:** „Ergänze einen Testfall für `<Verhalten>` (Rezept B). Anforderung laut `<Quelle>`.
> Pflicht oder beratend: `<…>`. Ergänze auch Webseite und Doku.“

> **Referenzlauf übernehmen:** „Hier ist der Bericht von `make acceptance BROKER=<…>`: `<Datei/Ausgabe>`.
> Übernimm ihn als Referenzlauf (Rezept C) und aktualisiere Webseite und Stand.“

> **Webseite:** „Erweitere den Baukasten um `<Baustein/Aktion/Lernschritt>` (Rezept D). Ergebnisse nur
> aus vorhandenen Läufen.“

> **Spec-Update:** „ENTC-<…> legt fest: `<Inhalt, Quelle, Datum>`. Setze das um (Rezept E) und zeig mir,
> welche Ergebnisse sich dadurch ändern.“

> **Status:** „Schreib einen neuen Statusbericht (Rezept F) für `<Anlass/Empfänger>`.“

## 7. Definition of Done (vor jedem Commit)

- [ ] Unit- und Integrationstests grün: `cd sim && python3 -m unittest discover -s tests -t .`
      (im Container: `make sim-test`; Integrationstests brauchen lokal `mosquitto` und `openssl`)
- [ ] Generierte Dateien aktuell:
  - nach Änderungen an Flotte oder Generator `make fleet`
  - nach neuen Läufen, Fall-Texten oder **jeder Änderung am Skript der Webseite** `make web`
  - die Reproduzierbarkeits-Tests sind grün
- [ ] Doku nachgezogen: Anleitung DE und EN, `acceptance-harness.md`, Broker-README
- [ ] Bei Nutzer-sichtbaren Änderungen `VERSION` erhöht (`JJJJ-MM-TT-rN`)
- [ ] Keine Geheimnisse: `git diff --cached | grep -E "BEGIN [A-Z ]*PRIVATE KEY"` liefert nichts
- [ ] Keine Lauf-Ergebnisse, Zertifikate oder `sim/config.local.toml` im Commit
- [ ] Antwort an den Menschen nennt, was getestet wurde und was nicht (z. B. „ohne Docker“)

## 8. Git und Auslieferung

- Arbeit auf einem Branch (`claude/<thema>`), dann nach Absprache Merge oder Fast-Forward nach `main`.
  Nie Historie auf `main` umschreiben.
- ZIP für Nutzer ohne Git: `git archive --format=zip --prefix=enetec_mtls_lab/ -o enetec_mtls_lab.zip HEAD`.
  Lokale Ordner `certs/`, `results/` bleiben beim Entpacken über eine alte Version erhalten.
- Das Repo `Todo_API` hat mit diesem Lab nichts zu tun; dort nichts ablegen.

## 9. Wenn etwas unklar ist

Die KI hält an und fragt, wenn:
- eine Entscheidung aus Abschnitt 2 nötig ist,
- eine Quelle fehlt oder sich Quellen widersprechen,
- ein Lauf nicht ausführbar ist (kein Docker, keine Broker-Instanz).

Sie liefert dann, was ohne diese Entscheidung geht, und sagt genau, was fehlt.
