# Eingebunden von den urspruenglichen PoC-Tests 04-10 (ROOT gesetzt).
# Sie nutzen das fruehere Topic-Schema eicp/v1/sim/{plantId}/gateways/{gatewayId}/d2c|c2d/...
# und Client ID = CN (Wire-Profil lab-eicp). Standard des Labs ist seit 2026-10-08 v1.3
# (enetec/v1/{clientId}/state|cmd); dann bricht der Test mit einem Hinweis ab, statt falsch zu messen.
if ! grep -q '^topic .*eicp/v1/sim/' "$ROOT/mosquitto/config/acl"; then
  printf 'This original PoC test uses the earlier topic layout (wire profile lab-eicp).\n' >&2
  printf 'Switch the lab broker to it first:   make fleet WIRE=lab-eicp\n' >&2
  printf 'and back to v1.3 afterwards:          make fleet\n' >&2
  exit 2
fi
