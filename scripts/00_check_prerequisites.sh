#!/usr/bin/env sh
set -eu
for cmd in openssl docker; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing dependency: $cmd"; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required."; exit 1; }
echo "OK: prerequisites available."
openssl version
docker compose version
