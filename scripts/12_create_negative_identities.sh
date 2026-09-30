#!/usr/bin/env sh
# Negative Test-Identitaeten fuer die Identitaetstests (13_identity_tests.sh).
# Je Fall certs/negative/<fall>/client.key + client.crt, dazu certs/negative/crl.pem.
#
# Alle Faelle ausser unknown-gateway tragen die echte Gateway-ID als CN, damit
# jeweils genau eine Eigenschaft falsch ist (Aussteller, Gueltigkeit, EKU, Widerruf):
#   untrusted-ca    fremde CA mit identischem Namen "ENETEC Simulation Root CA"
#   self-signed     selbstsigniert
#   expired         Lab-CA, gueltig 2020-2021
#   not-yet-valid   Lab-CA, gueltig ab 2035
#   wrong-eku       Lab-CA, EKU nur serverAuth
#   revoked         Lab-CA, gueltig, in crl.pem widerrufen (keyCompromise)
#   unknown-gateway Lab-CA, gueltig, CN gw-sim-900001 (nicht in Flotte/ACL)
# Seriennummern ab 0xA000, getrennt von 01/02 (ca.srl ab 0x1000).
# Usage: sh scripts/12_create_negative_identities.sh [gateway-id]   (Standard gw-sim-000001)
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CA="$ROOT/certs/ca"
NEG="$ROOT/certs/negative"
TARGET="${1:-gw-sim-000001}"
UNKNOWN=gw-sim-900001

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ -r "$CA/ca.key" ] && [ -r "$CA/ca.crt" ] || die 'Lab CA missing. Run make init first.'

rm -rf "$NEG"
mkdir -p "$NEG/.ca/newcerts"
: > "$NEG/.ca/index.txt"
printf 'A000\n' > "$NEG/.ca/serial"
printf '1000\n' > "$NEG/.ca/crlnumber"

# Minimale "openssl ca"-Konfiguration: noetig fuer frei gesetzte Gueltigkeit und CRL.
cat > "$NEG/.ca/ca.cnf" <<CONF
[ca]
default_ca = lab

[lab]
dir = $NEG/.ca
database = \$dir/index.txt
new_certs_dir = \$dir/newcerts
serial = \$dir/serial
crlnumber = \$dir/crlnumber
certificate = $CA/ca.crt
private_key = $CA/ca.key
default_md = sha256
default_crl_days = 30
policy = any
unique_subject = no
copy_extensions = none

[any]
countryName = optional
organizationName = optional
commonName = supplied
CONF

# $1 Datei, $2 EKU, $3 CA:TRUE|FALSE, $4 CN, $5 keyUsage
profile() {
  cat > "$1" <<CONF
[req]
prompt = no
distinguished_name = dn

[dn]
C = IT
O = ENETEC-SIM
CN = $4

[v3]
basicConstraints = critical, CA:$3
keyUsage = critical, $5
extendedKeyUsage = $2
subjectKeyIdentifier = hash
CONF
}

new_key() {
  openssl ecparam -name prime256v1 -param_enc named_curve -genkey -noout -out "$1"
  chmod 600 "$1"
}

# $1 Fall, $2 CN, $3 EKU, weitere Argumente: Gueltigkeit fuer "openssl ca"
issue() {
  CASE=$1 CN=$2 EKU=$3
  shift 3
  DIR="$NEG/$CASE"
  mkdir -p "$DIR"
  new_key "$DIR/client.key"
  profile "$DIR/profile.cnf" "$EKU" FALSE "$CN" digitalSignature
  openssl req -new -key "$DIR/client.key" -out "$DIR/client.csr" -config "$DIR/profile.cnf"
  openssl ca -batch -notext -config "$NEG/.ca/ca.cnf" -in "$DIR/client.csr" -out "$DIR/client.crt" \
    -extfile "$DIR/profile.cnf" -extensions v3 "$@" 2> "$DIR/openssl.log" ||
    { cat "$DIR/openssl.log" >&2; die "openssl ca failed for $CASE"; }
}

printf 'Negative identities for %s -> %s\n' "$TARGET" "$NEG"

issue expired "$TARGET" clientAuth -startdate 200101000000Z -enddate 210101000000Z
issue not-yet-valid "$TARGET" clientAuth -startdate 350101000000Z -enddate 360101000000Z
issue wrong-eku "$TARGET" serverAuth -days 365
issue revoked "$TARGET" clientAuth -days 365
issue unknown-gateway "$UNKNOWN" clientAuth -days 365

openssl ca -config "$NEG/.ca/ca.cnf" -revoke "$NEG/revoked/client.crt" -crl_reason keyCompromise \
  2> "$NEG/revoked/revoke.log" || { cat "$NEG/revoked/revoke.log" >&2; die 'revocation failed'; }
openssl ca -config "$NEG/.ca/ca.cnf" -gencrl -out "$NEG/crl.pem" 2> "$NEG/.ca/gencrl.log" ||
  { cat "$NEG/.ca/gencrl.log" >&2; die 'CRL generation failed'; }

# Fremde CA mit identischem Namen: Namensgleichheit allein darf kein Vertrauen erzeugen.
ROGUE="$NEG/untrusted-ca"
mkdir -p "$ROGUE"
new_key "$ROGUE/rogue-ca.key"
profile "$ROGUE/rogue-ca.cnf" clientAuth TRUE 'ENETEC Simulation Root CA' 'keyCertSign, cRLSign'
openssl req -x509 -new -sha256 -days 3650 -key "$ROGUE/rogue-ca.key" -out "$ROGUE/rogue-ca.crt" \
  -config "$ROGUE/rogue-ca.cnf" -extensions v3
new_key "$ROGUE/client.key"
profile "$ROGUE/profile.cnf" clientAuth FALSE "$TARGET" digitalSignature
openssl req -new -key "$ROGUE/client.key" -out "$ROGUE/client.csr" -config "$ROGUE/profile.cnf"
openssl x509 -req -sha256 -days 365 -in "$ROGUE/client.csr" -CA "$ROGUE/rogue-ca.crt" \
  -CAkey "$ROGUE/rogue-ca.key" -CAcreateserial -out "$ROGUE/client.crt" \
  -extfile "$ROGUE/profile.cnf" -extensions v3 2> "$ROGUE/openssl.log"

SELF="$NEG/self-signed"
mkdir -p "$SELF"
new_key "$SELF/client.key"
profile "$SELF/profile.cnf" clientAuth FALSE "$TARGET" digitalSignature
openssl req -x509 -new -sha256 -days 365 -key "$SELF/client.key" -out "$SELF/client.crt" \
  -config "$SELF/profile.cnf" -extensions v3

printf '\n%-16s %-26s %s\n' CASE NOT_AFTER 'SUBJECT / ISSUER'
for CASE in untrusted-ca self-signed expired not-yet-valid wrong-eku revoked unknown-gateway; do
  CRT="$NEG/$CASE/client.crt"
  printf '%-16s %-26s %s\n' "$CASE" "$(openssl x509 -in "$CRT" -noout -enddate | cut -d= -f2)" \
    "$(openssl x509 -in "$CRT" -noout -subject | sed 's/^subject=//') / $(openssl x509 -in "$CRT" -noout -issuer | sed 's/^issuer=//')"
done
printf '\nCRL: %s (revoked: %s)\n' "$NEG/crl.pem" "$(openssl x509 -in "$NEG/revoked/client.crt" -noout -serial | cut -d= -f2)"
