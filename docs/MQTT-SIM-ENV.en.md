# ENETEC MQTT Simulation Environment: Development, Structure, Usage

**Date:** 2026-10-12 · **Related:** ENTC-63 (test harness), ENTC-58 (architecture), ENTC-59 (broker selection), ENTC-31 (certificates), ENTC-61 (message specification)

*Deutsche Fassung: [MQTT-SIM-ENV.md](MQTT-SIM-ENV.md)*

This document explains how the simulation environment came about, how it works, how to set it up and
how to use it. Details on individual topics are in the linked documents under `docs/mqtt-tests/` and
`brokers/`.

---

## 1. Purpose

ENETEC is moving from AWS IoT Core to Google Cloud. The MQTT backbone between gateways and cloud
needs a new broker for this. Before one is selected, the **gateway ↔ MQTT broker** communication layer
should be validated with simulated gateways, with results that anyone can reproduce and verify.

The environment answers four questions:

1. **Does a broker meet the security requirements?** (mTLS, identity, access rights, duplicate
   Client ID, QoS 1, sessions, logs, Last Will, restart, revocation) → the acceptance suite (`make acceptance`).
2. **Does it behave correctly under realistic traffic?** (24 hours of telemetry, outages, reconnect
   storm, commands to offline gateways) → the simulation (`make simulate`).
3. **How do two brokers compare directly?** → the comparison (`make compare`).
4. **What does the weighted decision basis look like?** → the decision matrix (`make decide`).
5. **How does it all fit together?** → the Baukasten (building kit) in the browser (`web/baukasten/index.html`).

It does not replace a decision. Cost, operations, support and scalability only enter the matrix as
sourced hand scores; open points stay open (see section 9).

**Since 2026-10-08** the lab speaks the topic layout of MQTT wire contract v1.3 by default:
`enetec/v1/{clientId}/state` (device → cloud) and `enetec/v1/{clientId}/cmd` (cloud → device), with a
Client ID derived from the serial number. The earlier layout stays available as `WIRE=lab-eicp`.

## 2. How it was developed

| Phase | What happened | Result |
|---|---|---|
| **1. Starting point** | A manual Docker lab with Mosquitto, a test CA and two gateways. Individual scripts (04–10) showed publishing, cross-gateway access, the Client ID gap, gateway replacement and ACL withdrawal on an active connection. | Good experiments, but no repeatable acceptance suite |
| **2. Synthetic fleet** | A fleet derived from the project documents: 6 plants, 10 gateways, 108 devices, 24 h of traffic calibrated to ~251 messages per gateway per day (from 2.51 M/day at ~10,000 gateways). Plus outages, a reconnect storm, buffer overflow, commands during outages. | Reproducible data (`sim/config.toml` → `synthetic/`); generates the ACL and all certificates |
| **3. Simulation** | Each gateway connects with its own certificate, sends QoS 1, loses the network (TCP drop), buffers, and reconnects with Clean Start = false. Two cloud stand-ins read d2c and send c2d. An evaluation compares plan and observation. | `make simulate`: 2,500/2,500 messages, 57/57 sessions resumed |
| **4. Acceptance harness (ENTC-63)** | 31 mandatory cases for 15 requirements (R01–R15), PASS/FAIL per requirement, exit 0 only if everything passes. What is measured is actual delivery, not just the return code. | `make acceptance` with reports and evidence |
| **5. Broker profiles** | The broker is replaceable: a profile (`sim/targets/*.toml`) describes address, certificate trust and log patterns. The tests stay the same. | `make acceptance BROKER=<profile>` |
| **6. Legacy and rotation** | The real AWS IoT certificate of test gateway `0000000000000005` had no CN (only `C=UK, ST=United`, RSA 2048). This led to the LEG and ROT cases. | R16/R17 (informational at first) |
| **7. More brokers** | Configuration for EMQX; until 08 Oct also HiveMQ (with lab extension) and Bevywise, dropped on 12 Oct (git history). New: Pro Mosquitto by Cedalo. | `make acceptance BROKER=emqx` or `BROKER=cedalo` |
| **8. Comparison** | Select two profiles, results side by side, effort classes per requirement. | `make compare A=… B=…` |
| **9. Wire contract v1.3** (08 Oct) | Topics `enetec/v1/{clientId}/state\|cmd`, Client ID as a pseudonym of the serial (ENTC-47; algorithm still open, a placeholder in the lab), registry certificate → serial → Client ID. The earlier layout remains as a compatibility profile. | `make acceptance` (v13), `WIRE=lab-eicp` |
| **10. Open cases from the Current State** (08 Oct) | Binary transport, Last Will (also to foreign topics), Message Expiry, payload sizes, broker restart, revocation and ACL withdrawal on an active connection. The last three need an action on the broker in the middle of the run (hooks). Plus the weighted decision matrix. | R18–R24, `make decide` |

**Lessons learned along the way**
- **Negative cases need a positive control.** Without it, "broker not reachable" would have been counted as "rejected". Now a timeout never counts as PASS, and without a passing control everything becomes INCONCLUSIVE.
- **A PUBACK alone proves nothing.** Whether access is blocked is measured by whether an authorized witness sees the message.
- **macOS ships LibreSSL.** The certificate scripts 12 and 15 therefore run in the container with OpenSSL 3.
- **`docker compose build` needs a terminal.** The image is built with `docker build -q`.
- **Identities must stay stable across runs.** If negative and legacy certificates were re-created on every run, the broker (registry, CRL) would no longer match. They are only re-issued when needed.
- **Changes to a running broker take time.** A withdrawal only counts once it takes effect within the observation window; waiting too briefly would have failed a broker that reloads every 2 s for the wrong reason.

## 3. Structure

```text
                      sim/config.toml  (fleet, traffic, outages, assumptions)
                              │ make fleet
        ┌─────────────────────┼──────────────────────────────┐
        ▼                     ▼                              ▼
  synthetic/              certificates (certs/)        broker permissions, generated:
  fleet.json              lab CA, per gateway/service, mosquitto/config/acl
  client_identities.tsv   negative, legacy, rotation   brokers/emqx/acl.conf
  dataset/*                                            (Pro Mosquitto uses the same acl as Mosquitto)
        │                     │
        ▼                     ▼
  sim container (Python, paho-mqtt 2.1, OpenSSL 3)
   ├─ acceptance : mandatory and advisory cases       ──►  results/acceptance-<run>/
   │     └─ hooks (restart, revocation, ACL withdrawal) ◄── scripts/13_acceptance.sh
   ├─ simulate   : 24 h of traffic against the broker ──►  results/simulation-<run>/
   ├─ compare    : two brokers side by side           ──►  results/compare-<A>-vs-<B>-<time>/
   └─ decide     : weighted matrix (decision.toml)    ──►  results/decision-<time>/
        │ MQTT 5 + mTLS
        ▼
  Broker under test: Mosquitto (lab reference) │ EMQX │ Pro Mosquitto (Cedalo, licence needed)
```

**Actors in the test:** each gateway has its own certificate (CN = the lab's Gateway ID) and an
authorized Client ID. In profile v13 that is a pseudonym of the serial, e.g. `gw-sim-000001` →
`c4b06565c3cea7d66c4a6`; in profile `lab-eicp` it is the CN. The cloud stand-ins
`svc-sim-cloud-ingest` (reads all `state`) and `svc-sim-cloud-command` (writes all `cmd`) stand for the
later Pub/Sub bridge and the command path. Peripheral devices are data only, not MQTT clients.

**Source rules.** Nothing is invented. In `sim/config.toml` every assumption is marked SOURCE
(project document), INTERPRETED, ASSUMPTION or OPEN. The Client ID derivation is a placeholder
(`lab-sha256-v0`) because the real algorithm is open. The simulation sends `telemetry.report` in the
format of `samples/telemetry.json` as a **synthetic JSON fixture**, not in the v1.3 binary format.
Payloads in the acceptance suite are opaque bytes.

### Directories

| Path | Contents |
|---|---|
| `sim/config.toml` | Configuration of the fleet, the traffic and the wire profile |
| `sim/decision.toml` | Weights, candidates and sourced hand scores of the decision matrix |
| `sim/enetec_sim/` | Python program (generator, simulation, acceptance, comparison, matrix) |
| `sim/targets/*.toml` | Broker profiles |
| `sim/tests/` | Unit and integration tests |
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

The first run takes a few minutes (pulling images, issuing certificates).

**Starting over:** `make clean` deletes certificates, broker data and logs. The results under
`results/` are kept. After `make init` or `make clean`, certificates are re-issued automatically
when needed.

## 5. Usage

| Command | Purpose |
|---|---|
| `make acceptance` | Acceptance against the lab Mosquitto. Exit 0 only if all mandatory cases pass |
| `make acceptance BROKER=emqx` | Acceptance against another profile (`make brokers` lists them: `mosquitto-lab`, `emqx`, `cedalo`) |
| `make acceptance WIRE=lab-eicp` | with the earlier topic layout and Client ID = CN |
| `make simulate` | 24 h of traffic, time-compressed (×720, about 2 minutes), then evaluation |
| `make simulate BROKER=emqx SPEED=2880 GATEWAYS=gw-sim-000001,gw-sim-000006` | with options |
| `make compare A=emqx B=mosquitto-lab` | compare two brokers (latest complete run per broker) |
| `make compare A=cedalo B=emqx FRESH=1` | run acceptance for both again, then compare |
| `make decide` | weighted decision matrix from `sim/decision.toml` and the latest runs |
| `make web` | refresh the data of the Baukasten web page from the repo (fleet, reference runs) |
| `make fleet` | Regenerate fleet, dataset, ACLs and certificates (after changing `sim/config.toml`); `make fleet WIRE=lab-eicp` for the individual tests 04–10 |
| `make sim-test` | Unit tests in the container |
| `make brokers` | Available profiles |
| `make clean` | Delete local certificates and broker data |

**Every run ends with a summary** (result, wire profile, requirements R01–R24 at a glance, cases not passed, broker
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
| N/A | The case does not apply to the selected wire profile (e.g. ID-03 under `lab-eicp`) |

### The cases

| Group | Cases | Checks |
|---|---|---|
| MTLS | 01–08 | valid certificate; no certificate, foreign CA, self-signed, expired, not yet valid, wrong EKU, revoked |
| ID | 01–03 | foreign Client ID; binding of permissions to the certificate; CN instead of the derived Client ID (v13 only) |
| DUP | 01 | duplicate Client ID: reject the new connection, keep the existing one |
| ACL | 01–14 | own `state`/`cmd` allowed; other gateway/installation, wrong direction, wildcard, unknown gateway denied; ACL-14 withdrawal on an active connection (advisory, hook) |
| QOS / SES / REC | 01–02 / 01–02 / 01 | QoS 1 incl. redelivery, persistent session, reconnect without a storm |
| PAY | 01–03 | binary transport byte-exact (mandatory); 128 B / 12 KB; above the packet limit (advisory) |
| LWT / EXP | 01–02 / 01 | Last Will on link loss (advisory); foreign Will topic blocked (mandatory); Message Expiry (advisory) |
| RST / REV | 01 / 01 | broker restart with session; revocation on an active connection (advisory, hooks) |
| LOG | 01–05 | connect, TLS errors, ACL denials, disconnects in the log; no keys in the log |
| LEG / ROT | 01–02 / 01–02 | legacy certificate without CN; rotation with overlap and rollback |

Full rules: [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md) (German).

### The Baukasten (building kit)

Open `web/baukasten/index.html` directly in a browser (no server, no Docker). The page is bilingual:
**DE | EN** at the top right (or `index.html?lang=en`).

- **Build:** drag installations, gateways, a broker and the cloud services from the block bar onto the
  mounting plate, or tap them.
- **Set up a gateway:** certificate (valid, expired, foreign CA, revoked …), Client ID (authorized,
  foreign, CN instead of derived), link, serial number.
- **Trigger actions:** send state, foreign topics, subscriptions, offline command, Last Will,
  revocation, permission withdrawal, broker restart, reconnect storm. Each action shows the flow and the
  result the selected broker **actually had in the lab**, with test case, requirement and observation
  from the reference report. Without a run it says "not measured".
- **Swap broker:** the bar above the cabinet shows every broker with its mandatory pass rate. A click
  swaps the broker and replays the last action there; the test log offers the same via "Same case on
  the other brokers".
- **Packet monitor:** below the cabinet the MQTT packets of the flow run along (simulated; the verdict
  comes from the lab run).
- **Learning path:** seven guided steps with progress.
- **Desk:** broker comparison per requirement, generated ACLs, glossary.
- **Export:** the layout becomes `sim/config.local.toml`. `make fleet` then creates exactly these
  gateways, with serial numbers, Client IDs and links as in the Baukasten. The file supplements
  `sim/config.toml` and is not checked in; back to the lab fleet with
  `rm sim/config.local.toml && make fleet`.

New reference runs reach the page through `web/baukasten/sources.toml` and `make web`.

**Page security:** it loads nothing from third parties (fonts are embedded, SIL OFL 1.1), sends
nothing anywhere and only runs its own script (Content Security Policy with a script hash written by
`make web`). The layout is only stored in your own browser (`localStorage`) and checked on load; a
tampered state is discarded.

## 6. Connecting your own broker

1. Copy a profile: `cp sim/targets/emqx.toml sim/targets/my-broker.toml`.
2. Fill in `name`, `host`, `port`, `server_ca` if needed, and under `[log]` the patterns for the
   broker log. With `lab_managed = false` the run does not start the broker itself.
3. Configure the broker from the fleet: trust the lab CA as client CA, require a client certificate,
   use the CN as identity, accept only the authorized Client ID (`synthetic/client_identities.tsv`),
   permissions from `synthetic/fleet.json` (per gateway only write its own `state` and read its own
   `cmd`; one direction each for the cloud stand-ins; deny everything else).
4. Optional `[effort]` in the profile: effort class per requirement
   (NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE / CUSTOM DEVELOPMENT / UNSUPPORTED).
5. Optional for restart, revocation and ACL withdrawal: `[hooks] crl_reload` / `acl_reload` in the
   profile (lab broker) or `SIM_HOOK_RESTART`, `SIM_HOOK_CRL_RELOAD`, `SIM_HOOK_ACL_RELOAD` (own broker).
6. `make acceptance BROKER=my-broker SIM_BROKER_LOG=/path/to/broker.log`
7. Add the candidate to `sim/decision.toml` so that it appears in `make decide`.

Existing profiles and guides: [`brokers/emqx/`](../brokers/emqx/README.md),
[`brokers/cedalo/`](../brokers/cedalo/README.md) (Pro Mosquitto, with licence notes and vendor information with sources; German).

## 7. Status of the results (2026-10-12)

**Wire profile v13 (current):**

| Broker | Mandatory cases | Advisory | Where tested |
|---|---|---|---|
| Mosquitto 2.0.18 (lab reference, basis of Pro Mosquitto) | 25 PASS, 3 FAIL (ID-01, ID-03, DUP-01), 6 PARTIAL | RST-01 FAIL (session gone after restart), REV-01 FAIL, ACL-14 PASS | locally (without Docker) |
| EMQX 5.8 (candidate, leading) | not run in the v13 profile yet | – | – |
| Pro Mosquitto (Cedalo, candidate) | profile and configuration prepared, no run yet (licence needed) | – | – |

**Profile lab-eicp (until 2026-10-01, historical):** Mosquitto 23 PASS / 2 FAIL / 6 PARTIAL,
EMQX 29/31 (Client ID binding, duplicate Client ID).

**Cedalo according to the vendor** (researched on 12 Oct, not checked in the lab; sources in
[`brokers/cedalo/README.md`](../brokers/cedalo/README.md)): native Google Pub/Sub bridge, HA cluster from
3 nodes, certificate management with revocation and disconnecting clients in the Management Center,
persistent queueing, audit trail. Nothing found on Client ID binding (R06), takeover protection (R11)
and certificates without CN (R16), exactly where open-source Mosquitto fails.

**Key findings**
- **Client ID binding (v13):** a derived Client ID requires the broker to look up the mapping certificate → authorized Client ID. Mosquitto cannot do this (ID-03 FAIL); for Pro Mosquitto and EMQX a solution (plugin, hook, registry lookup) is open.
- **Revocation on an active connection** needs more than a CRL at connect time: the broker has to disconnect affected sessions. Mosquitto with the lab configuration reaches neither open nor new connections; the Cedalo profile sets `crlfile`, and Cedalo also offers disconnecting clients from the Management Center.
- **Broker restart:** Mosquitto 2.0.18 wrote its persistence file, yet the session was gone after the restart (local run, to be repeated with the Docker image).
- **Mosquitto:** a Client ID that differs from the certificate is accepted and displaces the real session. A duplicate Client ID leads to session takeover. Denied subscriptions are acknowledged (only delivery stays blocked).
- **EMQX:** deny by default, direction separation and cross-gateway blocks pass completely, with the denial signalled (SUBACK 0x87). Like Mosquitto it fails on CN ≠ Client ID and on duplicate Client ID; in addition, wrong key usage (EKU), revocation (without CRL distribution points) and legacy certificates without CN are not caught (informational only).
- **Legacy certificates (AWS IoT)** contain no Gateway ID. A broker needs a registry mapping (fingerprint → Gateway ID), or the gateways get new certificates with the ID in the CN.
- **Duplicate Client ID** has a trade-off: after a silent connection loss the broker rejects reconnects until the keep-alive expires (up to about 180 s).

Reports: `docs/mqtt-tests/reference/`. Legacy analysis: [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md) (German).

## 8. Troubleshooting

| Message | Cause and solution |
|---|---|
| `No rule to make target 'acceptance'` | old folder or old ZIP. Check the version (`cat VERSION`, currently `2026-10-12-r3` or newer), unzip the new ZIP over the folder (`unzip -o`) |
| Baukasten says "No lab data embedded" | run `make web` in the lab folder and reload the page |
| Baukasten stays empty, console reports "Content Security Policy" | the page script was edited without running `make web`: `make web` writes the new script hash |
| `make fleet` creates a different fleet than expected | a `sim/config.local.toml` from the Baukasten is still there; back with `rm sim/config.local.toml && make fleet` |
| `This original PoC test uses the earlier topic layout` | the individual tests 04–10 need the earlier layout: `make fleet WIRE=lab-eicp`, back with `make fleet` |
| RST-01 / REV-01 / ACL-14 INCONCLUSIVE with `hook … not available` or `unsupported` | broker not started by the lab, or profile without `[hooks]`: set `SIM_HOOK_RESTART` / `SIM_HOOK_CRL_RELOAD` / `SIM_HOOK_ACL_RELOAD`. Does not change the acceptance result |
| `Different wire profiles` in `make compare` | the two runs use different topic layouts; rerun both with the same `WIRE` (`FRESH=1`) |
| `Negative identities failed` | old ZIP without the OpenSSL 3 fix, or Docker is not running |
| `failed to get console` / `pull access denied for enetec-sim` | old ZIP; the current version builds the image with `docker build -q` |
| `certs/... does not chain to the current lab CA` | certificates from an earlier CA; `make fleet` re-issues them, otherwise `make clean` |
| `Broker certificate has no SAN "cedalo"` | lab from an older version; `make clean && make acceptance BROKER=…` |
| `pull access denied` for `registry.cedalo.com` | `docker login registry.cedalo.com` with the credentials from the Cedalo trial; licence file to `brokers/cedalo/license/license.lic` |
| all cases INCONCLUSIVE | broker not reachable (port, host, is the container running?) |
| LOG cases INCONCLUSIVE | no broker log passed, or log patterns in the profile do not match: set `SIM_BROKER_LOG=…` and adjust the patterns |
| Port in use | another broker or container; `docker compose down`. Mosquitto uses 8883, EMQX 8884, Pro Mosquitto 8885 |
| Two runs interfere | do not start runs in parallel; they use the same Client IDs |

## 9. Limits and next steps

**Not covered:**
- Load with ~15,000 gateways
- HA failover (RST-01 only restarts a single node)
- Bootstrap phase (permission switch after claim)
- Application correlation `command_id` ↔ `origin_command_id` (needs real firmware)
- Integration with Google Pub/Sub

**Technical limits:**
- Connection loss is simulated as a TCP close.
- Broker timers run in real time, also with time-compressed traffic.
- Negative observations apply to the observation window (default 3 s).
- Log checks are pattern searches per profile.

**Next steps:**
1. Run EMQX (leading candidate) in the v13 profile; for ACL-14 configure a reload of the file ACL via the EMQX API as `acl_reload`.
2. Pro Mosquitto: request the 30-day trial, run `make acceptance BROKER=cedalo`, ask Cedalo about the open points (R06, R11, R16, Pub/Sub bridge, on-premises price) ([`brokers/cedalo/README.md`](../brokers/cedalo/README.md)).
3. Agree the weights in `sim/decision.toml` with SOLHEA/ENETEC and fill in the hand scores with sources.
4. Load test for the 15,000 connections and Pub/Sub integration, reported separately from functional acceptance.
5. Adopt the Client ID derivation algorithm (ENTC-47) and the packet limit (ENTC-61) once decided.

## 10. Further documents

| Document | Contents |
|---|---|
| [`STAND-2026-10-12.md`](STAND-2026-10-12.md) | Current status: candidates EMQX and Pro Mosquitto (Cedalo), next steps (German) |
| [`STAND-2026-10-08.md`](STAND-2026-10-08.md) | Status as of 08 Oct (historical, with HiveMQ and Bevywise; German) |
| [`../brokers/cedalo/README.md`](../brokers/cedalo/README.md) | Pro Mosquitto: setup, expectations, vendor information with sources (German) |
| [`mqtt-tests/acceptance-harness.md`](mqtt-tests/acceptance-harness.md) | Wire profile, requirements R01–R24, PASS rules, hooks, comparison, decision matrix (German) |
| [`../web/baukasten/index.html`](../web/baukasten/index.html) | Baukasten web page (German / English) |
| [`AI-PLAYBOOK.md`](AI-PLAYBOOK.md) | Rules and recipes for AI assistants in this repo (German) |
| [`mqtt-tests/synthetic-simulation.md`](mqtt-tests/synthetic-simulation.md) | Data model, assumptions, simulation, reference run (German) |
| [`mqtt-tests/legacy-certificates.md`](mqtt-tests/legacy-certificates.md) | Analysis of the AWS certificate, rotation, questions for ENETEC (German) |
| [`mqtt-tests/reference/`](mqtt-tests/reference/) | Reports of the reference runs and the comparison |
| [`../README.md`](../README.md) | The original lab and the individual tests 04–10 |
