#!/usr/bin/env sh
# Legacy- und Rotations-Identitaeten fuer die Acceptance-Faelle LEG-* und ROT-*.
#
# Legacy (wie das AWS-IoT-Zertifikat des Test-Gateways 0000000000000005):
#   RSA 2048, SHA-256, Subject nur "C=UK, ST=United" (KEIN CN/SAN), Key Usage
#   digitalSignature, keine EKU. Die Gateway-ID steht NICHT im Zertifikat.
#   -> certs/legacy/<gateway-id>/client.{key,crt}
#   -> certs/legacy/registry.tsv  (SHA-256-Fingerprint <TAB> Gateway-ID), das was ein
#      Broker per Registry-Lookup braeuchte (AWS: Zertifikat am Thing).
# Rotation (ENETEC-Ablauf: neuer Schluessel + CSR auf dem Geraet, nur CSR zur CA):
#   zweites Zertifikat fuer rotation_gateway, RSA 2048, CN = Gateway-ID, clientAuth
#   -> certs/rotation/<gateway-id>/client.{key,crt}
# Signiert von der Lab-CA (die AWS-interne CA wird nicht nachgebildet).
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
CA=certs/ca
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ -r "$CA/ca.key" ] && [ -r "$CA/ca.crt" ] || die 'Lab CA missing. Run make init first.'
[ -f synthetic/legacy_gateways.txt ] || die 'synthetic/legacy_gateways.txt missing. Run make fleet first.'
SUBJECT=$(sed -n 's/^subject = "\(.*\)"/\1/p' sim/config.toml)
ROTATION=$(sed -n 's/^rotation_gateway = "\(.*\)"/\1/p' sim/config.toml)
[ -n "$SUBJECT" ] && [ -n "$ROTATION" ] || die 'legacy.subject / legacy.rotation_gateway missing in sim/config.toml'

# $1 Verzeichnis, $2 Subject, $3 Extension-Block
issue() {
  mkdir -p "$1"
  printf '%s\n' "[ext]" "basicConstraints = critical, CA:FALSE" "keyUsage = critical, digitalSignature" \
    "subjectKeyIdentifier = hash" "authorityKeyIdentifier = keyid" "$3" > "$1/ext.cnf"
  # Schluessel + CSR wie auf dem Geraet: nur die CSR verlaesst das Geraet.
  openssl req -new -newkey rsa:2048 -nodes -sha256 -keyout "$1/client.key" -out "$1/client.csr" \
    -subj "$2" 2> "$1/openssl.log" || { cat "$1/openssl.log" >&2; die "CSR failed: $1"; }
  chmod 600 "$1/client.key"
  openssl x509 -req -sha256 -days 365 -in "$1/client.csr" -CA "$CA/ca.crt" -CAkey "$CA/ca.key" \
    -CAserial "$CA/ca.srl" -out "$1/client.crt" -extfile "$1/ext.cnf" -extensions ext \
    2>> "$1/openssl.log" || { cat "$1/openssl.log" >&2; die "signing failed: $1"; }
}

rm -rf certs/legacy certs/rotation
mkdir -p certs/legacy
: > certs/legacy/registry.tsv
while IFS= read -r GW; do
  [ -n "$GW" ] || continue
  issue "certs/legacy/$GW" "$SUBJECT" ''
  FP=$(openssl x509 -in "certs/legacy/$GW/client.crt" -noout -fingerprint -sha256 | cut -d= -f2)
  printf '%s\t%s\n' "$FP" "$GW" >> certs/legacy/registry.tsv
  printf 'legacy   %s  subject "%s"  %s\n' "$GW" "$SUBJECT" "$FP"
done < synthetic/legacy_gateways.txt

issue "certs/rotation/$ROTATION" "/C=IT/O=ENETEC-SIM/CN=$ROTATION" 'extendedKeyUsage = clientAuth'
printf 'rotation %s  new certificate (RSA 2048, CSR-based)\n' "$ROTATION"
