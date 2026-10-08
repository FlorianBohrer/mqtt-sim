#!/usr/bin/env sh
# Widerruf waehrend des Laufs (Acceptance-Fall REV-01, Hook "revoke"):
# widerruft certs/negative/revoke-live in der Lab-CA-Datenbank von Skript 12 und schreibt
# certs/negative/crl.pem neu. Der Broker muss die CRL danach neu laden (Profil [hooks] crl_reload).
# Laeuft im sim-Container (OpenSSL 3) bzw. mit SIM_LOCAL=1 lokal.
# Die Marke revoke-live/.revoked sorgt dafuer, dass der naechste make acceptance die
# Negativ-Identitaeten (und damit eine frische CRL) neu erzeugt.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
NEG="$ROOT/certs/negative"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ -f "$NEG/revoke-live/client.crt" ] && [ -f "$NEG/.ca/ca.cnf" ] || die 'revoke-live missing: run make negative-certs'

if [ ! -f "$NEG/revoke-live/.revoked" ]; then
  openssl ca -config "$NEG/.ca/ca.cnf" -revoke "$NEG/revoke-live/client.crt" -crl_reason keyCompromise \
    2> "$NEG/revoke-live/revoke.log" || { cat "$NEG/revoke-live/revoke.log" >&2; die 'revocation failed'; }
  : > "$NEG/revoke-live/.revoked"
fi
openssl ca -config "$NEG/.ca/ca.cnf" -gencrl -out "$NEG/.ca/crl.new" 2> "$NEG/.ca/gencrl.log" ||
  { cat "$NEG/.ca/gencrl.log" >&2; die 'CRL generation failed'; }
# In place: keeps the inode for brokers that mount the file directly.
cat "$NEG/.ca/crl.new" > "$NEG/crl.pem"
rm -f "$NEG/.ca/crl.new"
printf 'revoked: %s (serial %s); CRL %s\n' revoke-live \
  "$(openssl x509 -in "$NEG/revoke-live/client.crt" -noout -serial | cut -d= -f2)" "$NEG/crl.pem"
