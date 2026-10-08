# EMQX 5.8 für den ENTC-63-Harness

**Stand:** 2026-10-08 · **Bezug:** ENTC-59 (Broker-Vergleich), ENTC-63 (Abnahme)

EMQX läuft als zusätzlicher Compose-Service im Lab, mit derselben Lab-CA, denselben Zertifikaten
und derselben Flotte wie der Lab-Mosquitto. Ein Befehl startet ihn, konfiguriert ihn und testet ihn:

```bash
make clean && make acceptance BROKER=emqx
```

Am 2026-10-01 lief der Harness im Docker-Lab gegen EMQX 5.8.6 (Profil `lab-eicp`, 29/31 Pflichtfälle).
Im Wire-Profil v13 und mit den Fällen vom 2026-10-08 ist EMQX **noch nicht gelaufen**; das Profil hat
weiter den Status `template`, bis die Log-Muster bestätigt sind. Die Konfigurationsschlüssel
entsprechen EMQX 5.8 (HOCON).

## Wire-Profil v1.3 und neue Fälle (2026-10-08)

`make acceptance BROKER=emqx` nutzt jetzt `enetec/v1/{clientId}/state|cmd` und abgeleitete Client-IDs.
Die generierte `acl.conf` enthält bereits diese Topics, weiter am Username = CN.

| Fall | Erwartung (der Lauf liefert die Belege) |
|---|---|
| ID-01, ID-03 | FAIL wie ID-01 am 01.10.: EMQX prüft nicht, ob die Client-ID zur Zertifikatsidentität gehört. Dafür braucht es eine Authentifizierung gegen die Registry (HTTP-Auth/Hook) |
| PAY-03 | aktiv, weil das Profil `max_packet_bytes = 1048576` setzt (`mqtt.max_packet_size = 1MB`) |
| RST-01 | Neustart über `docker compose restart emqx`. Eine Session-Persistenz über Neustarts ist in `emqx.conf` nicht eingeschaltet; der Lauf zeigt, ob die Session trotzdem erhalten bleibt |
| REV-01 | `crl_reload = "none"`: EMQX prüft CRLs nur über den CRL-Verteilpunkt im Zertifikat, den die Lab-Zertifikate nicht haben → FAIL erwartet |
| ACL-14 | INCONCLUSIVE, bis ein Reload der Datei-ACL hinterlegt ist: `acl_reload` im Profil oder `SIM_HOOK_ACL_RELOAD` mit einem Aufruf der EMQX-REST-API bzw. CLI (noch nicht ausgearbeitet) |

## Dateien

| Datei | Zweck |
|---|---|
| `emqx.conf` | Broker-Konfiguration, im Container als `/opt/emqx/etc/emqx.conf` |
| `acl.conf` | aus `synthetic/fleet.json` generiert (`make fleet`), eine allow-Regel je Gateway und Richtung, am Ende `{deny, all}` |
| `../../sim/targets/emqx.toml` | Harness-Profil: Compose-Service `emqx`, Host `localhost:8884` bzw. `emqx:8883`, Log-Muster |

## Wie die ENETEC-Anforderungen umgesetzt sind

| Anforderung | Einstellung in `emqx.conf` |
|---|---|
| Nur mTLS | `listeners.ssl.default` mit `verify = verify_peer`, `fail_if_no_peer_cert = true`, TLS 1.2/1.3; TCP-, WS- und WSS-Listener aus |
| Identität aus dem Zertifikat | `mqtt.peer_cert_as_username = cn`, die ACL hängt am Username = CN |
| Deny-by-default | `authorization.no_match = deny` plus `{deny, all}.` am Ende der `acl.conf` |
| Ablehnung signalisieren | `deny_action = ignore` → PUBACK/SUBACK 0x87 bei MQTT 5 (`disconnect` würde den Client trennen) |
| ACL-Änderungen sofort wirksam | `authorization.cache.enable = false` |
| Persistente Session | `mqtt.session_expiry_interval = 2h`; der Client setzt Clean Start = false |
| Audit-Log | Konsole auf Level `info`; das Skript sammelt sie per `docker compose logs emqx` |

## Erwartung vor dem ersten Lauf

Das ist eine Einschätzung; der Lauf liefert die Belege.

| Fall | Erwartung | Begründung |
|---|---|---|
| MTLS-01…07, ID-02, ACL-01…05, ACL-07 | PASS | Standard-mTLS, ACL an CN gebunden |
| ACL-08…13 (Subscribe) | eher PASS statt PARTIAL wie bei Mosquitto | EMQX meldet verweigerte SUBSCRIBE mit 0x87 |
| ACL-06, ACL-13 | PASS | `no_match = deny` |
| ID-01 | FAIL | EMQX lehnt CN ≠ Client-ID nicht ab. Mit `peer_cert_as_clientid = cn` würde die Client-ID **ersetzt**: keine Verdrängung fremder Sessions, aber auch keine Ablehnung |
| DUP-01 | FAIL | Standard ist der Session-Takeover. ENETEC verlangt die Ablehnung; dafür braucht es eine Erweiterung (Hook/Plugin) |
| MTLS-08 (advisory) | FAIL | EMQX prüft CRLs über die CRL Distribution Points der Zertifikate (HTTP); die Lab-Zertifikate haben keine |
| LEG-01 (advisory) | FAIL | ohne CN kein Username → keine ACL-Regel trifft zu |
| LOG-01…04 | offen | Die Log-Muster im Profil sind breit gefasst und nach dem ersten Lauf zu schärfen |

## Hinweise

- **Port:** EMQX belegt auf dem Mac Port **8884**, der Lab-Mosquitto 8883. Beide können gleichzeitig laufen.
- **Dashboard:** http://localhost:18083 (Standard `admin` / `public`, nur lokal).
- **Lab-Zertifikate:** Das Broker-Zertifikat enthält jetzt den Namen `emqx`. Ein älteres Lab
  (ohne diesen Namen) meldet das; dann hilft `make clean`.
- **Stoppen:** `docker compose --profile emqx down`.
