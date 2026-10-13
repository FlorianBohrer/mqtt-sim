# ENETEC mTLS / X.509 Local Simulation Lab

A small local lab for reproducing the ENETEC prototype certificate flow with:

- OpenSSL
- EC P-256
- X.509
- CSR -> CA signing
- MQTT 5
- mutual TLS
- Plant/Gateway-scoped MQTT ACLs
- realistic ENETEC topic examples

## Architecture

```text
Local Test CA
   |
   | signs CSR
   v
Gateway X.509 certificate
   |
   | mTLS
   v
Mosquitto MQTT 5 broker
   |
   | certificate CN -> username
   v
Plant/Gateway ACL
   |
   v
eicp/v1/sim/{plantId}/gateways/{gatewayId}/...
```

The CA private key is used only for signing. It is never installed in a Gateway folder.

> **Guide:** development history, setup and usage of the whole simulation environment: [docs/MQTT-SIM-ENV.en.md](docs/MQTT-SIM-ENV.en.md) (English), [docs/MQTT-SIM-ENV.md](docs/MQTT-SIM-ENV.md) (Deutsch)
>
> **Baukasten:** build the simulation interactively in the browser, in German or English: open [web/baukasten/index.html](web/baukasten/index.html) (refresh its data, fonts and script hash with `make web`).
> **Explainer:** [web/erklaerung/index.html](web/erklaerung/index.html) follows one message through the whole chain; click through twelve stations and trigger connects, rejections and offline commands yourself ([docs/ERKLAERUNG.md](docs/ERKLAERUNG.md)).
> **AI playbook:** rules for AI assistants in this repo: [CLAUDE.md](CLAUDE.md), [docs/AI-PLAYBOOK.md](docs/AI-PLAYBOOK.md).

> **Topic layout (since 2026-10-08):** the acceptance harness and the simulation default to MQTT wire
> contract v1.3 (`enetec/v1/{clientId}/state|cmd`, derived Client ID). The original tests 04–10 in this
> README use the earlier layout `eicp/v1/sim/...` with Client ID = CN. Switch the lab broker to it first
> with `make fleet WIRE=lab-eicp`, and back with `make fleet`; otherwise the tests stop with a hint.

## 1. Prerequisites

On macOS you need:

```bash
openssl version
docker compose version
```

Docker Desktop is sufficient for the broker and MQTT CLI.

## 2. Initialize

```bash
make init
```

This generates:

```text
certs/
├── ca/
│   ├── ca.key
│   └── ca.crt
├── broker/
│   ├── broker.key
│   ├── broker.csr
│   └── broker.crt
└── gateways/
    ├── gw-sim-000001/
    │   ├── gateway.key
    │   ├── gateway.csr
    │   ├── gateway.crt
    │   └── gateway.cnf
    └── gw-sim-000002/
        └── ...
```

The Gateway certificate generation mirrors the prototype approach:

```bash
openssl req   -newkey ec   -pkeyopt ec_paramgen_curve:P-256   -nodes   -keyout gateway.key   -out gateway.csr   -config gateway.cnf
```

and signing:

```bash
openssl x509   -req   -in gateway.csr   -CA ca.crt   -CAkey ca.key   -CAcreateserial   -out gateway.crt   -days 365   -sha256   -extensions v3_req   -extfile gateway.cnf
```

## 3. Start MQTT broker

```bash
make up
```

Broker:

```text
mqtts://localhost:8883
```

It requires a client certificate signed by the local CA.

## 4. Inspect the certificate

```bash
make inspect
```

Look for:

```text
Subject CN = gw-sim-000001
Public Key = EC P-256
Key Usage = Digital Signature
Extended Key Usage = serverAuth, clientAuth
```

The lab intentionally keeps `serverAuth, clientAuth` because that matches the described prototype.
For a production MQTT-only credential, a narrower `clientAuth` profile should be evaluated.

## 5. Verify CA trust

```bash
make verify
```

Expected:

```text
gateway.crt: OK
```

## 6. Valid ENETEC-style publish

```bash
make valid-publish
```

Identity:

```text
certificate CN = gw-sim-000001
MQTT Client ID = gw-sim-000001
```

Allowed topic:

```text
eicp/v1/sim/plt_sim_001/gateways/gw-sim-000001/d2c/telemetry/report
```

## 7. Cross-Gateway ACL test

```bash
make cross-gateway
```

This authenticates with:

```text
CN = gw-sim-000001
```

but tries to publish into Gateway 2:

```text
eicp/v1/sim/plt_sim_002/gateways/gw-sim-000002/d2c/telemetry/report
```

Expected:

```text
AUTHENTICATED
     |
     v
cross-Gateway namespace
     |
     v
DENY
```

Check:

```bash
docker compose logs --tail=100 broker
```

## 8. Certificate identity vs MQTT Client ID

This is the most useful experiment:

```bash
make wrong-clientid
```

It deliberately uses:

```text
certificate CN = gw-sim-000001
MQTT Client ID = gw-sim-999999
```

ENETEC's target rule is:

```text
certificate identity
       ==
MQTT Client ID
       ==
Gateway ID
```

However, this Mosquitto configuration only proves:

```text
certificate CN -> authenticated username -> ACL
```

It does not automatically reject a CONNECT merely because:

```text
certificate CN != MQTT Client ID
```

If this test succeeds, that is intentional. It demonstrates the exact capability that must be verified in the final MQTT broker.

## 9. What is simulated vs. what is not

### Demonstrated locally

```text
P-256 key
   ->
CSR
   ->
CA signature
   ->
X.509 certificate
   ->
mTLS
   ->
certificate identity
   ->
topic authorization
```

### NOT demonstrated

This lab does not prove that the ESP32-C6 production firmware can:

```text
generate private key locally
        ->
keep it non-exportable
        ->
generate CSR locally
        ->
enroll against production PKI
        ->
install / rotate certificate
```

The private Gateway keys in this lab are generated by OpenSSL on your computer.

## 10. Recommended test order

```bash
make init
make up
make verify
make inspect
make valid-publish
make cross-gateway
make wrong-clientid
```

Then:

```bash
docker compose logs --tail=200 broker
```

## 11. Reset

```bash
make clean
```

This deletes the generated simulation keys and certificates.

Never copy real ENETEC private keys into this lab.

## 12. ENTC-63 acceptance harness (one command)

```bash
make clean && make acceptance
```

`make acceptance` (`scripts/13_acceptance.sh`) builds everything from a clean checkout:

- test CA
- synthetic fleet with one certificate per gateway
- generated ACL
- negative identities

It then starts the broker, runs the broker-agnostic acceptance cases and writes a PASS/FAIL
report per requirement to `results/acceptance-<run>/report.md`. The cases cover:

- mTLS positive/negative
- Client ID binding
- deny-by-default, d2c/c2d direction, cross-plant/cross-gateway
- duplicate Client ID
- QoS 1
- persistent session
- reconnect without storm
- broker logs

**It exits 0 only if every mandatory case passes.** The same harness runs against other
broker candidates via a target profile (`sim/targets/*.toml`).

Details and requirement mapping: [docs/mqtt-tests/acceptance-harness.md](docs/mqtt-tests/acceptance-harness.md).

**Results in the v1.3 profile (2026-10-13, Docker lab):** Mosquitto 2.1.2 25/34 mandatory cases (2.0.18 identical),
EMQX 5.8.6 31/34, EMQX with the lab registry prototype (`make acceptance BROKER=emqx-registry`)
34/34, accepted. Both brokers on their own fail on binding the Client ID to the certificate (R06) and
on duplicate Client IDs (R11); the registry prototype closes both for EMQX. Status and reports:
[docs/STAND-2026-10-13.md](docs/STAND-2026-10-13.md) (German).

## 13. Synthetic fleet and architecture simulation

```bash
make fleet
make simulate
```

`make fleet` creates the synthetic fleet, the 24 h dataset, the generated ACL and the certificates.
`make simulate` replays the dataset (QoS 1, outages, reconnect, commands) and verifies it.

The fleet config is `sim/config.toml`; the generated, committed data lives in `synthetic/`.
The data model, sources/assumptions and reference run are described in
[docs/mqtt-tests/synthetic-simulation.md](docs/mqtt-tests/synthetic-simulation.md).
