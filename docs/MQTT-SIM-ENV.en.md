# ENETEC MQTT Simulation Environment: Development, Structure, Usage

**Date:** 2026-10-01 · **Related:** ENTC-63 (test harness), ENTC-58 (architecture), ENTC-59 (broker selection), ENTC-31 (certificates), ENTC-61 (message specification)

*Deutsche Fassung: [MQTT-SIM-ENV.md](MQTT-SIM-ENV.md)*

This document explains how the simulation environment came about, how it works, how to set it up and
how to use it. Details on individual topics are in the linked documents under `docs/mqtt-tests/` and
`brokers/`.

---

## 1. Purpose

ENETEC is moving from AWS IoT Core to Google Cloud. The MQTT backbone between gateways and cloud
needs a new broker for this. Before one is selected, the **gateway ↔ MQTT broker** communication layer
should be validated with simulated gateways, with results that anyone can reproduce and verify.

The environment answers three questions:

1. **Does a broker meet the security requirements?** (mTLS, identity, access rights, duplicate
   Client ID, QoS 1, sessions, logs) → the acceptance suite (`make acceptance`).
2. **Does it behave correctly under realistic traffic?** (24 hours of telemetry, outages, reconnect
   storm, commands to offline gateways) → the simulation (`make simulate`).
3. **How do two brokers compare directly?** → the comparison (`make compare`).

It does not replace a decision. Cost, operations, support and scalability are not part of the
acceptance suite (see section 9).

## 2. How it was developed

| Phase | What happened | Result |
|---|---|---|
| **1. Starting point** | A manual Docker lab with Mosquitto, a test CA and two gateways. Individual scripts (04–10) showed publishing, cross-gateway access, the Client ID gap, gateway replacement and ACL withdrawal on an active connection. | Good experiments, but no repeatable acceptance suite |
| **2. Synthetic fleet** | A fleet derived from the project documents: 6 plants, 10 gateways, 108 devices, 24 h of traffic calibrated to ~251 messages per gateway per day (from 2.51 M/day at ~10,000 gateways). Plus outages, a reconnect storm, buffer overflow, commands during outages. | Reproducible data (`sim/config.toml` → `synthetic/`); generates the ACL and all certificates |
| **3. Simulation** | Each gateway connects with its own certificate, sends QoS 1, loses the network (TCP drop), buffers, and reconnects with Clean Start = false. Two cloud stand-ins read d2c and send c2d. An evaluation compares plan and observation. | `make simulate`: 2,500/2,500 messages, 57/57 sessions resumed |
| **4. Acceptance harness (ENTC-63)** | 31 mandatory cases for 15 requirements (R01–R15), PASS/FAIL per requirement, exit 0 only if everything passes. What is measured is actual delivery, not just the return code. | `make acceptance` with reports and evidence |
| **5. Broker profiles** | The broker is replaceable: a profile (`sim/targets/*.toml`) describes address, certificate trust and log patterns. The tests stay the same. | `make acceptance BROKER=<profile>` |
| **6. Legacy and rotation** | The real AWS IoT certificate of test gateway `0000000000000005` had no CN (only `C=UK, ST=United`, RSA 2048). This led to the LEG and ROT cases. | R16/R17 (informational at first) |
| **7. More brokers** | Configurations for Bevywise, EMQX and HiveMQ. HiveMQ CE has no authorization of its own, so there is a small lab extension. | HiveMQ passes 31/31, also in the Docker run |
| **8. Comparison** | Select two profiles, results side by side, effort classes per requirement. | `make compare A=… B=…` |

**Lessons learned along the way**
- **Negative cases need a positive control.** Without it, "broker not reachable" would have been counted as "rejected". Now a timeout never counts as PASS, and without a passing control everything becomes INCONCLUSIVE.
- **A PUBACK alone proves nothing.** Whether access is blocked is measured by whether an authorized witness sees the message.
- **macOS ships LibreSSL.** The certificate scripts 12 and 15 therefore run in the container with OpenSSL 3.
- **`docker compose build` needs a terminal.** The image is built with `docker build -q`.
- **Identities must stay stable across runs.** If negative and legacy certificates were re-created on every run, the broker (registry, CRL) would no longer match. They are only re-issued when needed.

## 3. Structure

```text
                      sim/config.toml  (fleet, traffic, outages, assumptions)
                              │ make fleet
        ┌─────────────────────┼──────────────────────────────┐
        ▼                     ▼                              ▼
  synthetic/            certificates (certs/)        broker permissions, generated:
  fleet.json            lab CA, per gateway/service, mosquitto/config/acl
  dataset/*             negative, legacy, rotation   brokers/emqx/acl.conf
                                                     brokers/hivemq/permissions.tsv
        │                     │
        ▼                     ▼
  sim container (Python, paho-mqtt 2.1, OpenSSL 3)
   ├─ acceptance : 31 mandatory cases + advisory cases ──►  results/acceptance-<run>/
   ├─ simulate   : 24 h of traffic against the broker  ──►  results/simulation-<run>/
   └─ compare    : two brokers side by side            ──►  results/compare-<A>-vs-<B>-<time>/
        │ MQTT 5 + mTLS
        ▼
  Broker under test: Mosquitto │ HiveMQ CE + extension │ EMQX │ Bevywise (external)
```

**Actors in the test:** each gateway has its own certificate (Client ID = Gateway ID = CN). The
cloud stand-ins `svc-sim-cloud-ingest` (reads all d2c) and `svc-sim-cloud-command` (writes all c2d)
stand for the later Pub/Sub bridge and the command path. Peripheral devices are data only, not MQTT
clients (as in EICP).

**Source rules.** Nothing is invented. In `sim/config.toml` every assumption is marked SOURCE
(project document), INTERPRETED, ASSUMPTION or OPEN. The only message is `telemetry.report` in the
format of `samples/telemetry.json`; commands run in the neutral namespace `c2d/simulation/…`. Payloads
in the acceptance suite are opaque random bytes.

### Directories

| Path | Contents |
|---|---|
| `sim/config.toml` | Configuration of the fleet and traffic |
| `sim/enetec_sim/` | Python program (generator, simulation, acceptance, comparison) |
| `sim/targets/*.toml` | Broker profiles |
| `sim/tests/` | 30 unit and integration tests |
| `synthetic/` | Generated fleet and dataset (checked in, reproducible) |
| `scripts/` | Certificates and start scripts; scripts 04–10 are the original individual tests |
| `brokers/<broker>/` | Configuration and guide per broker |
| `docs/mqtt-tests/` | Detailed docs and reference reports |
| `certs/`, `results/`, `data/` | Created locally, **not** checked in |

## 4. Setup

**Prerequisites:** Docker (with Docker Compose v2) and `make`. Python is not needed; it runs in the
container. macOS and Linux are supported.

```bash
mkdir -p ~/Projects/enetec
unzip -q ~/Downloads/enetec_mtls_lab.zip -d ~/Projects/enetec
cd ~/Projects/enetec/enetec_mtls_lab
cat VERSION
```

The lab is a self-contained folder without Git, GitHub or any other dependency. Keep it at a fixed
path without spaces and without iCloud sync (e.g. `~/Projects/enetec/`), because `certs/` contains
private lab keys.

**Installing a new version:** download the new ZIP and unzip it over the existing folder. `results/`,
`certs/` and `data/` are kept because they are not part of the ZIP:

```bash
unzip -o -q ~/Downloads/enetec_mtls_lab.zip -d ~/Projects/enetec
cat ~/Projects/enetec/enetec_mtls_lab/VERSION
```

The version is in the file `VERSION` (also `make version`). If the browser saved the ZIP under another
name (e.g. `enetec_mtls_lab (1).zip`), use that name.


**Note for zsh (macOS):** in an interactive terminal, `#` at the start of a line or after a command is not a comment by default. Copy only the commands without comments, or run `setopt interactive_comments` once.

Nothing else is needed. On the first run, `make acceptance` builds everything itself:

1. Image `enetec-sim:local` (Python 3.12, paho-mqtt, OpenSSL 3)
2. Test CA, broker certificate, certificates for all gateways and services
3. Negative, legacy and rotation identities
4. The broker (with an image build, depending on the profile)

The first run takes a few minutes, longer for HiveMQ because of the Maven build.

**Starting over:** `make clean` deletes certificates, broker data and logs. The results under
`results/` are kept. After `make init` or `make clean`, certificates are re-issued automatically
when needed.

## 5. Usage

| Command | Purpose |
|---|---|
| `make acceptance` | Acceptance against the lab Mosquitto. Exit 0 only if all mandatory cases pass |
| `make acceptance BROKER=hivemq` | Acceptance against another profile (`make brokers` lists them) |
| `make simulate` | 24 h of traffic, time-compressed (×720, about 2 minutes), then evaluation |
| `make simulate BROKER=hivemq SPEED=2880 GATEWAYS=gw-sim-000001,gw-sim-000006` | with options |
| `make compare A=hivemq B=mosquitto-lab` | compare two brokers (latest complete run per broker) |
| `make compare A=hivemq B=emqx FRESH=1` | run acceptance for both again, then compare |
| `make fleet` | Regenerate fleet, dataset, ACLs and certificates (after changing `sim/config.toml`) |
| `make sim-test` | Unit tests in the container |
| `make brokers` | Available profiles |
| `make clean` | Delete local certificates and broker data |

**Every run ends with a summary** (result, requirements R01–R17 at a glance, cases not passed, broker
limitations, path to the evidence). After a run that did not pass, make prints one more line
`make: *** Error 1`; that is just make and means exit code 1.

### Reading the results

Result folder `results/acceptance-<time>/`: `report.md` (table), `report.json`, `summary.txt`,
`events.jsonl` (every observation), `broker.log`.

| Value | Meaning |
|---|---|
| PASS | Required behaviour observed |
| FAIL | Opposite behaviour observed |
| PARTIAL | Access is effectively blocked, but the rejection is not signalled |
| INCONCLUSIVE | No evidence (broker not reachable, setup error, log missing) |
| advisory | Informational case for an open decision; does not count towards acceptance |

### The cases

| Group | Cases | Checks |
|---|---|---|
| MTLS | 01–08 | valid certificate; no certificate, foreign CA, self-signed, expired, not yet valid, wrong EKU, revoked |
| ID | 01–02 | certificate ≠ Client ID; binding of permissions to the certificate |
| DUP | 01 | duplicate Client ID: reject the new connection, keep the existing one |
| ACL | 01–13 | own d2c/c2d allowed; other gateway/plant, wrong direction, wildcard, unknown gateway denied |
| QOS / SES / REC | 01–02 / 01–02 / 01 | QoS 1 incl. redelivery, persistent session, reconnect without a storm |
| LOG | 01–05 | connect, TLS errors, ACL denials, disconnects in the log; no keys in the log |
| LEG / ROT | 01–02 / 01–02 | legacy certificate without CN; rotation with overlap and rollback |

Full rules: [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md) (German).

## 6. Connecting your own broker

1. Copy a profile: `cp sim/targets/emqx.toml sim/targets/my-broker.toml`.
2. Fill in `name`, `host`, `port`, `server_ca` if needed, and under `[log]` the patterns for the
   broker log. With `lab_managed = false` the run does not start the broker itself.
3. Configure the broker from the fleet: trust the lab CA as client CA, require a client certificate,
   use the CN as identity, permissions from `synthetic/fleet.json` (per gateway only write its own
   `d2c` and read its own `c2d`; one direction each for the cloud stand-ins; deny everything else).
4. Optional `[effort]` in the profile: effort class per requirement
   (NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE / CUSTOM DEVELOPMENT / UNSUPPORTED).
5. `make acceptance BROKER=my-broker SIM_BROKER_LOG=/path/to/broker.log`

Existing profiles and guides: [`brokers/emqx/`](../brokers/emqx/README.md),
[`brokers/hivemq/`](../brokers/hivemq/README.md), [`brokers/bevywise/`](../brokers/bevywise/README.md) (German).

## 7. Status of the results (2026-10-01)

| Broker | Mandatory cases | Where tested |
|---|---|---|
| HiveMQ CE 2026.5 + ENETEC extension | **31/31 PASS, accepted** | locally and in the Docker lab on macOS (two runs) |
| Mosquitto 2.0.18 (lab) | 23 PASS, 2 FAIL, 6 PARTIAL | locally (Docker run pending) |
| EMQX 5.8 | 29/31 PASS, **not accepted** (Client ID binding, duplicate Client ID); denied subscriptions are signalled | Docker lab on macOS |
| Bevywise | configuration prepared; no broker available, run without evidence (all INCONCLUSIVE) | – |

**Key findings**
- **Mosquitto:** a Client ID that differs from the certificate is accepted and displaces the real session. A duplicate Client ID leads to session takeover. Denied subscriptions are acknowledged (only delivery stays blocked).
- **EMQX:** deny by default, direction separation and cross-gateway blocks pass completely, with the denial signalled (SUBACK 0x87). Like Mosquitto it fails on CN ≠ Client ID and on duplicate Client ID; in addition, wrong key usage (EKU), revocation (without CRL distribution points) and legacy certificates without CN are not caught (informational only).
- **HiveMQ CE** has no authorization of its own. The requirements are only met with a lab extension (identity, Client ID binding, duplicate rejection, revocation, deny by default). For production: connect it to the backend registry, or use the commercial Enterprise Security Extension.
- **Legacy certificates (AWS IoT)** contain no Gateway ID. A broker needs a registry mapping (fingerprint → Gateway ID), or the gateways get new certificates with the ID in the CN.
- **Duplicate Client ID** has a trade-off: after a silent connection loss the broker rejects reconnects until the keep-alive expires (up to about 180 s).

Reports: `docs/mqtt-tests/reference/`. Legacy analysis: [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md) (German).

## 8. Troubleshooting

| Message | Cause and solution |
|---|---|
| `No rule to make target 'acceptance'` | old folder or old ZIP. Check the version (`cat VERSION`, currently `2026-10-01-r1` or newer), unzip the new ZIP over the folder (`unzip -o`) |
| `Negative identities failed` | old ZIP without the OpenSSL 3 fix, or Docker is not running |
| `failed to get console` / `pull access denied for enetec-sim` | old ZIP; the current version builds the image with `docker build -q` |
| `certs/... does not chain to the current lab CA` | certificates from an earlier CA; `make fleet` re-issues them, otherwise `make clean` |
| `Broker certificate has no SAN "hivemq"` | lab from an older version; `make clean && make acceptance BROKER=…` |
| all cases INCONCLUSIVE | broker not reachable (port, host, is the container running?) |
| LOG cases INCONCLUSIVE | no broker log passed, or log patterns in the profile do not match: set `SIM_BROKER_LOG=…` and adjust the patterns |
| Port in use | another broker or container; `docker compose down`. Mosquitto uses 8883, EMQX 8884, HiveMQ 8885 |
| Two runs interfere | do not start runs in parallel; they use the same Client IDs |

## 9. Limits and next steps

**Not covered:**
- Load with ~15,000 gateways
- Broker restart and HA failover
- Revocation on an existing connection (only tests 09/10 as individual scripts)
- Bootstrap phase (permission switch after claim)
- LWT
- Payloads up to 12 KB and oversize
- Integration with Google Pub/Sub

**Technical limits:**
- Connection loss is simulated as a TCP close.
- Broker timers run in real time, also with time-compressed traffic.
- Negative observations apply to the observation window (default 3 s).
- Log checks are pattern searches per profile.

**Next steps:**
1. Run Mosquitto in the Docker lab and Bevywise against a real instance, then compare all brokers.
2. Weighted decision matrix (cost, operations, support, scalability) in addition to acceptance.
3. Load test for the 15,000 connections.
4. Add the open mandatory cases (restart, failover, revocation on an active connection, bootstrap).
5. Prepare the results as a Jira comment for ENTC-63/ENTC-59.

## 10. Further documents

| Document | Contents |
|---|---|
| [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md) | Requirements R01–R17, PASS rules, broker comparison (German) |
| [`mqtt-tests/synthetic-simulation.md`](mqtt-tests/synthetic-simulation.md) | Data model, assumptions, simulation, reference run (German) |
| [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md) | Analysis of the AWS certificate, rotation, questions for ENETEC (German) |
| [`mqtt-tests/reference/`](mqtt-tests/reference/) | Reports of the reference runs and the comparison |
| [`../README.md`](../README.md) | The original lab and the individual tests 04–10 |
