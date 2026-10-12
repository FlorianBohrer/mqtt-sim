#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CA="$ROOT/certs/ca"
BR="$ROOT/certs/broker"

mkdir -p "$CA" "$BR"

echo "[1/4] Generate P-256 named-curve simulation CA key"

openssl ecparam \
  -name prime256v1 \
  -param_enc named_curve \
  -genkey \
  -noout \
  -out "$CA/ca.key"

chmod 600 "$CA/ca.key"

echo "[2/4] Generate simulation CA certificate"

cat > "$CA/ca.cnf" <<'CONF'
[req]
prompt = no
distinguished_name = dn
x509_extensions = v3_ca

[dn]
C = IT
O = ENETEC-SIM
CN = ENETEC Simulation Root CA

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
CONF

openssl req \
  -x509 \
  -new \
  -sha256 \
  -key "$CA/ca.key" \
  -days 3650 \
  -out "$CA/ca.crt" \
  -config "$CA/ca.cnf" \
  -extensions v3_ca

printf "1000\n" > "$CA/ca.srl"

cat > "$BR/broker.cnf" <<'CONF'
[req]
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
C = IT
O = ENETEC-SIM
CN = broker

[v3_req]
basicConstraints = critical, CA:FALSE
subjectAltName = @alt_names
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = broker
DNS.2 = localhost
DNS.3 = emqx
DNS.4 = cedalo
IP.1 = 127.0.0.1
CONF

echo "[3/4] Generate broker P-256 named-curve key + CSR"

openssl ecparam \
  -name prime256v1 \
  -param_enc named_curve \
  -genkey \
  -noout \
  -out "$BR/broker.key"

chmod 600 "$BR/broker.key"

openssl req \
  -new \
  -key "$BR/broker.key" \
  -out "$BR/broker.csr" \
  -config "$BR/broker.cnf"

echo "[4/4] Sign broker CSR"

openssl x509 \
  -req \
  -in "$BR/broker.csr" \
  -CA "$CA/ca.crt" \
  -CAkey "$CA/ca.key" \
  -CAserial "$CA/ca.srl" \
  -out "$BR/broker.crt" \
  -days 365 \
  -sha256 \
  -extensions v3_req \
  -extfile "$BR/broker.cnf"

echo "CA and broker certificate created."
