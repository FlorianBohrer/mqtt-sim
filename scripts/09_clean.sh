#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
docker compose down -v 2>/dev/null || true
rm -rf certs/ca/* certs/broker/* certs/gateways/* data/* logs/*
echo "Lab cleaned."
