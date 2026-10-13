#!/usr/bin/env sh
# Prepare step of profile emqx-registry (sim/targets/emqx-registry.toml): a REST API key that EMQX
# loads at start (api_key.bootstrap_file) and the registry uses for its duplicate check.
# Lab only; the key lives in certs/ (not in Git) and is created once.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DIR="$ROOT/certs/emqx-registry"
mkdir -p "$DIR"
if [ ! -s "$DIR/api_key.txt" ]; then
  printf 'registry:%s\n' "$(openssl rand -hex 24)" > "$DIR/api_key.txt"
fi
# Read inside the containers as their own user (EMQX uid 1000); on the Mac Docker Desktop maps this.
chmod 644 "$DIR/api_key.txt"
echo "EMQX API key for the registry: $DIR/api_key.txt"
