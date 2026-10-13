# EMQX + Registry: Lab-Prototyp für R06 und R11

**Stand:** 2026-10-13 · **Bezug:** ENTC-59 (Broker-Vergleich), ENTC-63 (Abnahme), ENTC-47 (Client-ID)

EMQX allein besteht 31 von 34 Pflichtfällen ([`brokers/emqx/`](../emqx/README.md)). Es fehlen die
Bindung der Client-ID an das Zertifikat (R06: ID-01, ID-03) und der Schutz vor einer stillen
Übernahme durch eine zweite Verbindung (R11: DUP-01). Dieser Prototyp schließt beide Lücken mit
Bordmitteln von EMQX und einem kleinen Dienst:

```bash
make clean && make acceptance BROKER=emqx-registry
```

**Ergebnis (2026-10-13, EMQX 5.8.6, zwei Läufe):** **ACCEPTED**, 34 von 34 Pflichtfällen. Bericht:
[`2026-10-13-emqx-5.8.6-registry-v13.md`](../../docs/mqtt-tests/reference/2026-10-13-emqx-5.8.6-registry-v13.md).
Die beratenden Fälle sind wie bei EMQX ohne Registry (MTLS-07, MTLS-08, REV-01, LEG-01, EXP-01 FAIL,
ACL-14 PARTIAL).

## Wie es funktioniert

```
Gateway --mTLS--> EMQX --HTTP POST /auth--> Registry --GET /api/v5/clients/{id}--> EMQX REST-API
                       <-- allow / deny ---
```

1. EMQX prüft wie bisher das Zertifikat (mTLS) und setzt den Username auf den CN.
2. Der **HTTP-Authenticator** (`brokers/emqx-registry/emqx.conf`) schickt bei jedem CONNECT
   Client-ID, Username und Zertifikats-CN an die Registry.
3. Die **Registry** ([`brokers/registry/registry.py`](../registry/registry.py)) erlaubt die Verbindung
   nur, wenn
   - der CN zur Flotte gehört (`synthetic/fleet.json`; unbekannte Zertifikate und Zertifikate ohne CN
     werden abgelehnt),
   - die Client-ID genau die ist, die zu diesem CN gehört (R06), und
   - keine Verbindung mit dieser Client-ID offen ist (R11; Abfrage der EMQX-REST-API). Für einen
     Reconnect nach einem Abbruch wartet sie bis zu 3 s, bis EMQX die alte Verbindung abgebaut hat.
4. Kann die Registry nicht entscheiden (Fehler, API nicht erreichbar), lehnt sie ab.

EMQX antwortet bei Ablehnung mit CONNACK 0x87 (Not authorized). Die erste Verbindung arbeitet weiter.

## Dateien

| Datei | Zweck |
|---|---|
| `emqx.conf` | bindet `brokers/emqx/emqx.conf` unverändert ein und ergänzt den HTTP-Authenticator und den API-Schlüssel |
| `../registry/registry.py` | Registry-Dienst, nur Python-Standardbibliothek; läuft im Image `python:3.12-alpine` |
| `../../scripts/19_emqx_registry.sh` | legt den REST-API-Schlüssel an (`certs/emqx-registry/api_key.txt`, nicht in Git) |
| `../../sim/targets/emqx-registry.toml` | Harness-Profil: Compose-Services `emqx-registry` und `registry`, Port 8886 |
| `../../sim/tests/test_registry.py` | Entscheidungsregeln der Registry als Unit-Tests |

Die Registry ist im Compose-Netz unter `registry:8080` erreichbar, nicht vom Host aus. Ihre
Entscheidungen stehen je Zeile in `docker compose --profile emqx-registry logs registry`.

## Grenzen des Prototyps

- **Nicht für den Betrieb gebaut.** Die Registry liest die synthetische Flotte aus einer Datei, hat
  keine Hochverfügbarkeit und keine eigene Authentifizierung im Compose-Netz. Im Betrieb steht hier
  die echte Registry aus ENTC-47 (Zertifikat → Seriennummer → Client-ID), redundant und abgesichert.
- **Zielkonflikt R11:** Bricht ein Link still ab (kein TCP-Abbau), hält EMQX die alte Verbindung bis
  zum Ablauf des Keep-alive (1,5 × 120 s). So lange lehnt die Registry jeden Reconnect als doppelt
  ab. Die Gateways puffern in dieser Zeit (im Lab bis 50 Meldungen).
- **Legacy-Zertifikate ohne CN** (R16) werden abgelehnt. Für eine Zuordnung über den Fingerprint
  müsste das Zertifikat im Authenticator-Aufruf mitkommen; nicht getestet.
- **Abhängigkeit:** Jeder Verbindungsaufbau wartet auf die Registry. Fällt sie aus, kommt kein Gerät
  mehr herein (fail closed). Das ist gewollt, verlangt aber Redundanz.

## Simulation

`make simulate BROKER=emqx-registry` (10 Gateways, 24 h in 2 Minuten, 57 Netzabbrüche): zwei von drei
Läufen PASS mit 10/10 Prüfungen; alle Reconnects nach einem Abbruch kamen durch (die Registry lehnte
keinen ab). Im ersten Lauf kam der letzte Schwung von 50 gepufferten Meldungen eines Gateways nicht
innerhalb des 5-s-Abklingfensters bei Cloud-Ingest an, obwohl EMQX ihn mit PUBACK 0 angenommen hatte.
Die Registry prüft nur den Verbindungsaufbau und liegt nicht auf diesem Weg. Cloud-Ingest hat eine
Session mit Expiry > 0 und bekommt seine Nachrichten damit über den Durable Storage von EMQX; dort
liegt vermutlich die Verzögerung. Ohne Registry trat sie in drei Läufen nicht auf. Ursache offen.
