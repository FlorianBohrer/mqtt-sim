# Broker comparison — HiveMQ CE 2026.5 + enetec-identity extension vs Mosquitto lab broker

Generated 2026-10-01T09:28:01+00:00 from acceptance runs A `acceptance-20261001T092610Z-9559` (localhost:8885) and B `acceptance-20261001T092702Z-9771` (localhost:8883).

**HiveMQ CE 2026.5 + enetec-identity extension is closer to acceptance: 0 vs 8 mandatory case(s) not passed.**

| | Broker | Result | Mandatory PASS | FAIL | PARTIAL | INCONCLUSIVE |
|---|---|---|---|---|---|---|
| A | HiveMQ CE 2026.5 + enetec-identity extension | ACCEPTED | 31/31 | 0 | 0 | 0 |
| B | Mosquitto lab broker | NOT ACCEPTED | 23/31 | 2 | 6 | 0 |

## Requirements

| ID | Requirement | A | B | Better | Effort A | Effort B |
|---|---|---|---|---|---|---|
| R01 | mTLS with an individual X.509 certificate per simulated gateway | **PASS** | **PASS** | = | CONFIGURATION: tls-tcp-listener, truststore | CONFIGURATION: require_certificate, cafile |
| R02 | Connection without client certificate is rejected | **PASS** | **PASS** | = | CONFIGURATION: client-authentication-mode REQUIRED | CONFIGURATION: require_certificate |
| R03 | Certificate signed by an untrusted CA is rejected | **PASS** | **PASS** | = | CONFIGURATION: truststore | CONFIGURATION: cafile |
| R04 | Invalid certificates (validity, key usage, revocation) are rejected | **PASS** | **PASS** | = | CUSTOM DEVELOPMENT: CRL check in the extension; validity is native | CONFIGURATION: validity checked; revocation needs crlfile (not set in lab config) |
| R05 | Certificate identity is bound to the Gateway ID (authorization follows the certificate) | **PASS** | **PASS** | = | CUSTOM DEVELOPMENT: CE has no ACL; extension maps CN to permissions | CONFIGURATION: use_identity_as_username + acl_file |
| R06 | MQTT Client ID = Gateway ID is enforced (otherwise the broker limitation is documented) | **PASS** | **FAIL** | A | CUSTOM DEVELOPMENT: enforced in the extension (Enterprise Security Extension: unverified) | UNSUPPORTED: CN == Client ID not enforced (ID-01 FAIL); custom plugin untested |
| R07 | ACLs deny by default | **PASS** | **PARTIAL** | A | CUSTOM DEVELOPMENT: permissions.tsv in the extension | CONFIGURATION: acl_file; denied SUBSCRIBE is not signalled (PARTIAL) |
| R08 | A gateway publishes only to its own d2c namespace | **PASS** | **PASS** | = | CUSTOM DEVELOPMENT: extension | CONFIGURATION: acl_file |
| R09 | A gateway subscribes only to its own c2d namespace | **PASS** | **PARTIAL** | A | CUSTOM DEVELOPMENT: extension | CONFIGURATION: acl_file; denied SUBSCRIBE is not signalled (PARTIAL) |
| R10 | Cross-plant and cross-gateway topic access is denied | **PASS** | **PARTIAL** | A | CUSTOM DEVELOPMENT: extension | CONFIGURATION: acl_file; denied SUBSCRIBE is not signalled (PARTIAL) |
| R11 | A duplicate Client ID does not silently take over the active session | **PASS** | **FAIL** | A | CUSTOM DEVELOPMENT: isClientConnected check in the extension | UNSUPPORTED: session takeover (DUP-01 FAIL); custom plugin untested |
| R12 | QoS 1: acknowledged, at-least-once delivery incl. redelivery after connection loss | **PASS** | **PASS** | = | NATIVE: MQTT 5 QoS 1 | NATIVE: MQTT 5 QoS 1 |
| R13 | Clean Start = false resumes the persistent session across disconnect/reconnect | **PASS** | **PASS** | = | NATIVE: persistent sessions | NATIVE: persistent sessions |
| R14 | Reconnect can be exercised without a reconnect storm | **PASS** | **PASS** | = | NATIVE: sessions survive; backoff is a client matter | NATIVE: sessions survive; backoff is a client matter |
| R15 | Security-relevant broker logs are available and contain no keys or credentials | **PASS** | **PASS** | = | CUSTOM DEVELOPMENT: ENETEC-AUDIT lines from the extension; TLS rejections not logged by default | CONFIGURATION: log_type, connection_messages |
| R16 | Legacy certificates without Gateway ID (AWS IoT profile) are mapped to the right gateway | **advisory PASS** | **advisory FAIL** | A | CUSTOM DEVELOPMENT: fingerprint registry in the extension | UNSUPPORTED: certificate without CN has no identity (LEG-01 FAIL) |
| R17 | Certificate rotation: old and new certificate overlap, switch with rollback | **advisory PASS** | **advisory PASS** | = | CONFIGURATION: two certificates for one CN work | CONFIGURATION: two certificates for one CN work |

## Cases with different results

| Case | Test | A | B | A observed | B observed |
|---|---|---|---|---|---|
| MTLS-08 | Revoked certificate (CRL; revocation strategy OPEN, ENTC-58/31) (advisory) | **PASS** | **FAIL** | REJECTED (CONNACK 135) | ACCEPTED (CONNACK 0) |
| ID-01 | Certificate of gateway A with Client ID of gateway B | **PASS** | **FAIL** | REJECTED (CONNACK 133) | ACCEPTED (CONNACK 0); legitimate session of gw-sim-000002 DISPLACED |
| DUP-01 | Second connection with the Client ID of an active gateway | **PASS** | **FAIL** | new: REJECTED (CONNACK 133); existing: still connected and publishing | new: ACCEPTED (CONNACK 0); existing: closed by server DISCONNECT (reason 0 Normal disconnection) |
| ACL-08 | A subscribes to B's c2d namespace (other plant) | **PASS** | **PARTIAL** | SUBACK [135]; delivered 0/1 | SUBACK [1]; delivered 0/1 (nothing delivered, but subscription not signalled as denied) |
| ACL-09 | C subscribes to B's c2d namespace (same plant, other gateway) | **PASS** | **PARTIAL** | SUBACK [135]; delivered 0/1 | SUBACK [1]; delivered 0/1 (nothing delivered, but subscription not signalled as denied) |
| ACL-10 | A subscribes to its own d2c namespace (wrong direction) | **PASS** | **PARTIAL** | SUBACK [135]; delivered 0/1 | SUBACK [1]; delivered 0/1 (nothing delivered, but subscription not signalled as denied) |
| ACL-11 | A subscribes to B's d2c telemetry (other plant) | **PASS** | **PARTIAL** | SUBACK [135]; delivered 0/1 | SUBACK [1]; delivered 0/1 (nothing delivered, but subscription not signalled as denied) |
| ACL-12 | A subscribes to the whole tree with a wildcard | **PASS** | **PARTIAL** | SUBACK [135]; delivered 0/2 | SUBACK [1]; delivered 0/2 (nothing delivered, but subscription not signalled as denied) |
| ACL-13 | Valid certificate, Gateway ID unknown to the fleet: publish and subscribe | **PASS** | **PARTIAL** | publish: PUBACK 135; delivered 0; disconnected; subscribe: SUBACK [135]; delivered 0/1 | publish: PUBACK 135; delivered 0; subscribe: SUBACK [1]; delivered 0/1 (nothing delivered, but subscription not signalled as denied) |
| LEG-01 | Legacy certificate (RSA 2048, no CN/SAN) connects as its gateway and publishes (advisory) | **PASS** | **FAIL** | 0000000000000005: PUBACK 0; delivered 1 | 0000000000000005: REJECTED (CONNACK 134) |

Effort classes: NATIVE / CONFIGURATION / PLUGIN / EXTERNAL SERVICE / CUSTOM DEVELOPMENT / UNSUPPORTED. They are the lab assessment recorded in the broker profiles, based on the observed results. This comparison states facts and does not select a provider: weights (cost, operations, support, scale) are not part of the acceptance suite.
