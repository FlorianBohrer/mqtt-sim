#!/usr/bin/env sh
# Paket zum Einrichten einer Bevywise-MQTTRoute-Installation mit den Lab-Identitaeten:
#   brokers/bevywise/generated/bundle/
#     Certificate/root/root.crt        Lab-CA (vertraut den Client-Zertifikaten)
#     Certificate/server/server.crt    Server-Zertifikat (SAN = lokal oder BEVYWISE_HOST)
#     Certificate/server/server.key
#     conf/*.example                   TLS-/ACL-Werte fuer broker.conf / mqtt.conf
#     acl-requests.json                ACL-Regeln je Client-ID (fuer apply-acl.sh)
#
#   make bevywise-bundle                              Broker laeuft lokal auf dem Mac (localhost)
#   make bevywise-bundle BEVYWISE_HOST=mqtt.example.com   Broker laeuft unter diesem Namen / dieser IP
#
# Voraussetzung: make init und make fleet. Die Dateinamen/Ordner stammen aus der Bevywise-Doku
# (Certificate/root, Certificate/server); gegen eine echte Installation noch nicht geprueft.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"
OUT=brokers/bevywise/generated/bundle
NAME="${BEVYWISE_HOST:-}"
[ -r certs/ca/ca.crt ] && [ -r certs/ca/ca.key ] || { echo 'Lab CA missing: run make init first.' >&2; exit 1; }
[ -f brokers/bevywise/generated/acl-requests.json ] || { echo 'ACL requests missing: run make bevywise-config first.' >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/Certificate/root" "$OUT/Certificate/server" "$OUT/conf"
cp certs/ca/ca.crt "$OUT/Certificate/root/root.crt"
if [ -n "$NAME" ]; then
  # Server certificate for the host name / IP under which the harness reaches the broker.
  case "$NAME" in
    *[!0-9.]*) SAN="DNS:$NAME" ;;
    *)         SAN="IP:$NAME" ;;
  esac
  openssl ecparam -name prime256v1 -param_enc named_curve -genkey -noout -out "$OUT/Certificate/server/server.key"
  openssl req -new -key "$OUT/Certificate/server/server.key" -out "$OUT/server.csr" -subj "/C=IT/O=ENETEC-SIM/CN=$NAME"
  printf 'basicConstraints = CA:FALSE\nkeyUsage = digitalSignature\nextendedKeyUsage = serverAuth\nsubjectAltName = %s\n' "$SAN" > "$OUT/server.ext"
  openssl x509 -req -sha256 -days 365 -in "$OUT/server.csr" -CA certs/ca/ca.crt -CAkey certs/ca/ca.key \
    -CAserial certs/ca/ca.srl -out "$OUT/Certificate/server/server.crt" -extfile "$OUT/server.ext" >/dev/null 2>&1
  rm -f "$OUT/server.csr" "$OUT/server.ext"
  echo "Server certificate for $NAME ($SAN) signed by the lab CA."
else
  cp certs/broker/broker.crt "$OUT/Certificate/server/server.crt"
  cp certs/broker/broker.key "$OUT/Certificate/server/server.key"
  echo 'Server certificate: lab broker certificate (SAN localhost, 127.0.0.1).'
fi
chmod 600 "$OUT/Certificate/server/server.key"
cp brokers/bevywise/conf/*.example "$OUT/conf/"
cp brokers/bevywise/generated/acl-requests.json "$OUT/acl-requests.json"
cat <<MSG

Bundle: $OUT
Next:
  1. Copy Certificate/root and Certificate/server into the Bevywise folder ./Certificate/
  2. Put the values from conf/broker.conf.example / conf/mqtt.conf.example into conf/ of the installation
     (TLS_ENABLED, TLS_PORT_NO - choose 8886 to avoid the lab's 8883 - and TOPIC_ACL = TRUE), restart the broker
  3. Import the ACL: BEVYWISE_API_URL=https://<host>:<api-port> ./brokers/bevywise/apply-acl.sh
  4. Set host/port in sim/targets/bevywise.toml, then: make acceptance BROKER=bevywise
MSG
