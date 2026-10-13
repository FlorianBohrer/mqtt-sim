# EMQX 5.8 für den ENTC-63-Harness

**Stand:** 2026-10-13 · **Bezug:** ENTC-59 (Broker-Vergleich), ENTC-63 (Abnahme)

EMQX läuft als zusätzlicher Compose-Service im Lab, mit derselben Lab-CA, denselben Zertifikaten
und derselben Flotte wie der Lab-Mosquitto. Ein Befehl startet ihn, konfiguriert ihn und testet ihn:

```bash
make clean && make acceptance BROKER=emqx
```

**Ergebnis im Profil v1.3 (2026-10-13, EMQX 5.8.6, Docker-Lab):** 31 von 34 Pflichtfällen bestanden,
nicht abgenommen. Es fehlen nur die Bindung der Client-ID an das Zertifikat (ID-01, ID-03 → R06) und
der Schutz vor einer stillen Session-Übernahme (DUP-01 → R11). Bericht:
[`2026-10-13-emqx-5.8.6-v13.md`](../../docs/mqtt-tests/reference/2026-10-13-emqx-5.8.6-v13.md).
Das Profil `sim/targets/emqx.toml` hat den Status `verified`.

## Ergebnisse je Fall

| Fall | Ergebnis | Was dahintersteckt |
|---|---|---|
| MTLS-01…06, ID-02, ACL-01…13, QOS, SES, REC, PAY, LWT | PASS | Standard-mTLS, ACL am CN, verbotene PUBLISH **und** SUBSCRIBE mit 0x87 abgelehnt |
| ID-01, ID-03 | FAIL | EMQX prüft nicht, ob die Client-ID zur Zertifikatsidentität gehört; die fremde Session wird verdrängt |
| DUP-01 | FAIL | MQTT-Standard: die neue Verbindung übernimmt, die alte wird getrennt |
| LOG-01…05 | PASS | LOG-01 nur mit der Regel `audit_client_connected` (siehe unten) |
| MTLS-07 (beratend) | FAIL | Der Listener von 5.8.6 kennt keine EKU-Prüfung. Die Option `verify_peer_ext_key_usage` steht zwar in den Dashboard-Texten, wird aber nicht übernommen (2026-10-13 geprüft) |
| MTLS-08, REV-01 (beratend) | FAIL | EMQX prüft CRLs nur über den CRL-Verteilpunkt im Zertifikat; die Lab-Zertifikate haben keinen |
| RST-01 (beratend) | PASS | mit `durable_sessions`; ohne sie FAIL |
| EXP-01 (beratend) | **FAIL** | mit `durable_sessions` liefert EMQX auch Commands aus, deren Message Expiry abgelaufen ist; ohne sie PASS |
| ACL-14 (beratend) | PARTIAL | nach dem Entzug kein PUBLISH mehr, ein bestehendes Abo liefert aber weiter |
| LEG-01 (beratend) | FAIL | ohne CN kein Username, also greift keine ACL-Regel |

Den **Zielkonflikt** RST-01 gegen EXP-01 belegt ein zweiter Lauf ohne Durable Sessions:
[`2026-10-13-emqx-5.8.6-v13-ohne-durable-sessions.md`](../../docs/mqtt-tests/reference/2026-10-13-emqx-5.8.6-v13-ohne-durable-sessions.md).

## Dateien

| Datei | Zweck |
|---|---|
| `emqx.conf` | Broker-Konfiguration, im Container als `/opt/emqx/etc/emqx.conf` |
| `acl.conf` | aus `synthetic/fleet.json` generiert (`make fleet`), eine allow-Regel je Gateway und Richtung, am Ende `{deny, all}` |
| `../../sim/targets/emqx.toml` | Harness-Profil: Compose-Service `emqx`, Host `localhost:8884` bzw. `emqx:8883`, Log-Muster, Hooks, Aufwand je Anforderung |

## Wie die ENETEC-Anforderungen umgesetzt sind

| Anforderung | Einstellung |
|---|---|
| Nur mTLS | `listeners.ssl.default` mit `verify = verify_peer`, `fail_if_no_peer_cert = true`, TLS 1.2/1.3; TCP-, WS- und WSS-Listener aus |
| Identität aus dem Zertifikat | `mqtt.peer_cert_as_username = cn`, die ACL hängt am Username = CN |
| Deny-by-default | `authorization.no_match = deny` plus `{deny, all}.` am Ende der `acl.conf` |
| Ablehnung signalisieren | `deny_action = ignore` → PUBACK/SUBACK 0x87 bei MQTT 5 (`disconnect` würde den Client trennen) |
| ACL-Änderungen sofort wirksam | `authorization.cache.enable = false`; die geänderte Datei liest `emqx ctl conf reload --merge` neu ein (Profil: `acl_reload = "exec:…"`) |
| Persistente Session | `mqtt.session_expiry_interval = 2h`; der Client setzt Clean Start = false |
| Session über Neustart | `durable_sessions.enable = true`; verlangt bei lokalem Speicher `cluster.discovery_strategy = singleton`. Ein Cluster bräuchte den replizierten Speicher `builtin_raft`, den das Open-Source-Image nicht enthält |
| Audit-Log | Konsole auf Level `info` (Ablehnungen, Trennungen, TLS-Fehler). Angenommene Verbindungen schreibt die Regel `audit_client_connected` mit Client-ID und CN; im Betrieb gehört das Ereignis an eine Log-Senke (HTTP, Kafka, Pub/Sub) statt auf die Konsole. Das eingebaute Audit-Log gibt es nur in der Enterprise-Ausgabe |

## Was für die Abnahme noch fehlt

1. **R06 und R11:** eine Authentifizierung, die Zertifikat (CN oder Fingerprint) und Client-ID gegen
   die Registry prüft und eine falsche oder doppelte Client-ID ablehnt, z. B. der HTTP-Authenticator
   von EMQX gegen einen kleinen Registry-Dienst. Noch nicht gebaut und nicht gemessen.
2. **R20 gegen R22:** bei EMQX klären, ob neuere Versionen die Message Expiry in Durable Sessions
   beachten.
3. **Widerruf (R23):** CRL-Verteilpunkte in die Zertifikate oder OCSP; offene Verbindungen müssten
   zusätzlich über die REST-API getrennt werden.

## Hinweise

- **Port:** EMQX belegt auf dem Host Port **8884**, der Lab-Mosquitto 8883. Beide können gleichzeitig laufen.
- **Dashboard:** http://localhost:18083 (Standard `admin` / `public`, nur lokal).
- **Lab-Zertifikate:** Das Broker-Zertifikat enthält den Namen `emqx`. Ein älteres Lab (ohne diesen
  Namen) meldet das; dann hilft `make clean`.
- **Stoppen:** `docker compose --profile emqx down`. Die Durable Sessions liegen im Container und
  sind nach `down` weg; ein `restart` behält sie.
