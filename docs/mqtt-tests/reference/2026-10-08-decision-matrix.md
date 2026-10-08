# Broker decision matrix (ENTC-59)

Generated 2026-10-08T14:38:27+00:00.

**No favourite: open criteria on the shortlist (EMQX: security_acceptance, operations_ha, scale, gcp_integration, vendor_support, cost; Bevywise MQTTRoute / CrystalMQ: security_acceptance, operations_ha, scale, gcp_integration, vendor_support, cost; Cedalo / Pro Mosquitto: security_acceptance, development_effort, operations_ha, scale, gcp_integration, vendor_support, cost).**

## Weights

| Criterion | Weight |
|---|---|
| Security acceptance (ENTC-63 mandatory cases) | 35 % |
| Custom development needed for standard requirements | 20 % |
| HA / clustering / operations | 15 % |
| Scale: ~15,000 concurrent connections | 10 % |
| GCP Pub/Sub integration | 10 % |
| Vendor responsiveness / support | 5 % |
| Cost (license and operations) | 5 % |

## Scores (0..5)

| Candidate | Shortlist | Total | Coverage | Security acceptance (ENTC-63 mandatory cases) | Custom development needed for standard requirements | HA / clustering / operations | Scale: ~15,000 concurrent connections | GCP Pub/Sub integration | Vendor responsiveness / support | Cost (license and operations) |
|---|---|---|---|---|---|---|---|---|---|---|
| EMQX | yes | — | 20 % | — | 3.47 | — | — | — | — | — |
| Bevywise MQTTRoute / CrystalMQ | yes | — | 20 % | — | 1 | — | — | — | — | — |
| Cedalo / Pro Mosquitto | yes | — | 0 % | — | — | — | — | — | — | — |
| HiveMQ (CE + ENETEC lab extension) | no | — | 60 % | 5 | 2.83 | — | — | — | 1 | — |
| Mosquitto 2.0 (lab baseline) | no | — | 55 % | 4.12 | 3.65 | — | — | — | — | — |

## Sources

### EMQX
- **Security acceptance (ENTC-63 mandatory cases)**: — (open) — no usable acceptance run for profile emqx
- **Custom development needed for standard requirements**: 3.47 (lab) — 17 requirements classified in sim/targets/emqx.toml (profile status template)
- **HA / clustering / operations**: — (open) — OPEN
- **Scale: ~15,000 concurrent connections**: — (open) — OPEN
- **GCP Pub/Sub integration**: — (open) — OPEN
- **Vendor responsiveness / support**: — (open) — OPEN
- **Cost (license and operations)**: — (open) — OPEN

### Bevywise MQTTRoute / CrystalMQ
- **Security acceptance (ENTC-63 mandatory cases)**: — (open) — no usable acceptance run for profile bevywise
- **Custom development needed for standard requirements**: 1 (hand) — SOURCE: vendor assessment (Current State 08.10 §9): certificate mapping/revocation, dynamic Gateway-Plant authorization and clustered enforcement need customer-specific work, 4-6 weeks
- **HA / clustering / operations**: — (open) — OPEN
- **Scale: ~15,000 concurrent connections**: — (open) — OPEN
- **GCP Pub/Sub integration**: — (open) — OPEN
- **Vendor responsiveness / support**: — (open) — OPEN
- **Cost (license and operations)**: — (open) — OPEN

### Cedalo / Pro Mosquitto
- **Security acceptance (ENTC-63 mandatory cases)**: — (open) — OPEN
- **Custom development needed for standard requirements**: — (open) — OPEN
- **HA / clustering / operations**: — (open) — OPEN
- **Scale: ~15,000 concurrent connections**: — (open) — OPEN
- **GCP Pub/Sub integration**: — (open) — OPEN
- **Vendor responsiveness / support**: — (open) — OPEN
- **Cost (license and operations)**: — (open) — OPEN

### HiveMQ (CE + ENETEC lab extension)
- **Security acceptance (ENTC-63 mandatory cases)**: 5 (lab) — run acceptance-20261008T143031Z-7874 (topics v13, client id derived (lab-sha256-v0)): 34/34 PASS, 0 PARTIAL, 0 FAIL, 0 INCONCLUSIVE
- **Custom development needed for standard requirements**: 2.83 (lab) — 24 requirements classified in sim/targets/hivemq.toml
- **HA / clustering / operations**: — (open) — OPEN
- **Scale: ~15,000 concurrent connections**: — (open) — OPEN
- **GCP Pub/Sub integration**: — (open) — OPEN
- **Vendor responsiveness / support**: 1 (hand) — SOURCE: Current State 08.10 §9, commercial provider not responding
- **Cost (license and operations)**: — (open) — OPEN

### Mosquitto 2.0 (lab baseline)
- **Security acceptance (ENTC-63 mandatory cases)**: 4.12 (lab) — run acceptance-20261008T143626Z-16133 (topics v13, client id derived (lab-sha256-v0)): 25/34 PASS, 6 PARTIAL, 3 FAIL, 0 INCONCLUSIVE
- **Custom development needed for standard requirements**: 3.65 (lab) — 23 requirements classified in sim/targets/mosquitto-lab.toml
- **HA / clustering / operations**: — (open) — OPEN
- **Scale: ~15,000 concurrent connections**: — (open) — OPEN
- **GCP Pub/Sub integration**: — (open) — OPEN
- **Vendor responsiveness / support**: — (open) — OPEN
- **Cost (license and operations)**: — (open) — OPEN

Rules: lab = computed from lab evidence (acceptance run, broker profile); hand = scored in sim/decision.toml with a source; open = no evidence yet, never counted as 0. Total = weighted mean over all criteria, only when nothing is open. The weights are a proposal (ASSUMPTION) to be agreed with SOLHEA/ENETEC; this matrix documents the decision basis, it does not select a provider.
