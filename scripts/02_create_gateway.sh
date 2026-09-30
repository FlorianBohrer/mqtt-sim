#!/usr/bin/env sh
set -eu

[ "$#" -ge 1 ] || {
  echo "Usage: $0 <gateway-id>"
  exit 1
}

GW="$1"
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CA="$ROOT/certs/ca"
DIR="$ROOT/certs/gateways/$GW"

mkdir -p "$DIR"

cat > "$DIR/gateway.cnf" <<CONF
[req]
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
C = IT
O = ENETEC-SIM
CN = $GW

[v3_req]
basicConstraints = critical, CA:FALSE
subjectAltName = @alt_names
keyUsage = critical, digitalSignature
extendedKeyUsage = clientAuth

[alt_names]
DNS.1 = $GW.local
IP.1 = 127.0.0.1
CONF

echo "[1/2] Generate $GW P-256 named-curve key + CSR"

openssl ecparam \
  -name prime256v1 \
  -param_enc named_curve \
  -genkey \
  -noout \
  -out "$DIR/gateway.key"

chmod 600 "$DIR/gateway.key"

openssl req \
  -new \
  -key "$DIR/gateway.key" \
  -out "$DIR/gateway.csr" \
  -config "$DIR/gateway.cnf"

echo "[2/2] Sign $GW CSR"

openssl x509 \
  -req \
  -in "$DIR/gateway.csr" \
  -CA "$CA/ca.crt" \
  -CAkey "$CA/ca.key" \
  -CAserial "$CA/ca.srl" \
  -out "$DIR/gateway.crt" \
  -days 365 \
  -sha256 \
  -extensions v3_req \
  -extfile "$DIR/gateway.cnf"

echo "Created $DIR/gateway.crt"
