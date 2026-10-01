"""Synthetic fleet registry: plants, gateways, peripheral devices, service identities."""
import random
import uuid

from .config import gateway_base, parse_utc

SERIAL_RANGE = (100_000_000, 4_294_967_295)  # 32-bit hardware serial (EICP deviceId)


def weighted_choice(rng, table):
    keys = list(table)
    return rng.choices(keys, weights=[table[k] for k in keys])[0]


def uuid7(unix_ms, rng):
    value = (unix_ms << 80) | (0x7 << 76) | (rng.getrandbits(12) << 64) | (0b10 << 62) | rng.getrandbits(62)
    return str(uuid.UUID(int=value))


class _Serials:
    def __init__(self, rng):
        self.rng, self.used = rng, set()

    def next(self):
        serial = str(self.rng.randint(*SERIAL_RANGE))
        while serial in self.used:
            serial = str(self.rng.randint(*SERIAL_RANGE))
        self.used.add(serial)
        return serial


def build_fleet(cfg):
    fc = cfg['fleet']
    rng = random.Random(f"{cfg['seed']}:fleet")
    serials = _Serials(rng)
    pinned = {}
    for entry in fc.get('pinned', []):
        pinned.setdefault(entry['plant_id'], []).append(entry['gateway_id'])
    numbers = [int(g.rsplit('-', 1)[1]) for ids in pinned.values() for g in ids]
    next_no = max(numbers, default=0) + 1
    created_ms = int(parse_utc(cfg['dataset']['start']) * 1000)

    pinned_plants = list(pinned)
    plants, gateways = [], []
    for i in range(fc['plants']):
        if i < len(pinned_plants):
            plant_id = pinned_plants[i]
        else:
            created_ms -= rng.randint(1, 30 * 86400) * 1000
            plant_id = f'plt_{uuid7(created_ms, rng)}'
        plant_type = weighted_choice(rng, fc['plant_types'])
        ids = pinned.pop(plant_id, [])
        target = max(rng.randint(*fc['gateways_per_plant'][plant_type]), len(ids))
        while len(ids) < target:
            ids.append(f'gw-sim-{next_no:06d}')
            next_no += 1
        gateways += [_gateway(cfg, rng, serials, plant_id, plant_type, gw_id) for gw_id in ids]
        plants.append({'plant_id': plant_id, 'type': plant_type, 'gateways': ids})
    if pinned:
        raise ValueError(f'more pinned plants than fleet.plants: {sorted(pinned)}')

    base = cfg['topics']['base']
    services = [
        {'identity': cfg['services']['ingest'],
         'role': 'cloud-ingest (placeholder for the MQTT->Pub/Sub bridge)',
         'read': [f'{base}/+/gateways/+/d2c/#'], 'write': []},
        {'identity': cfg['services']['command'],
         'role': 'cloud-command (placeholder for the backend command path)',
         'read': [], 'write': [f'{base}/+/gateways/+/c2d/#']},
    ]
    return {
        'note': 'SYNTHETIC lab fleet generated from sim/config.toml. Not ENETEC data; '
                'message semantics are defined by ENTC-61 / EICP v1.4.',
        'generator': {'name': 'enetec_sim', 'seed': cfg['seed'], 'config_sha256': cfg['_sha256']},
        'topics': dict(cfg['topics']),
        'plants': plants,
        'gateways': gateways,
        'services': services,
        'legacy_gateways': _legacy(cfg),
    }


def _gateway(cfg, rng, serials, plant_id, plant_type, gateway_id):
    fc, cl = cfg['fleet'], cfg['climate']
    devices = [{'serial_number': serials.next(), 'device_class': 'system_controller'}]
    for _ in range(rng.randint(*fc['room_devices_per_gateway'][plant_type])):
        devices.append({
            'serial_number': serials.next(),
            'device_class': 'room_device',
            # Generator parameters for the room-climate model, not device metadata.
            'simulation': {
                'setpoint_c': round(rng.uniform(*cl['setpoint_c']), 1),
                'base_rh_pct': round(rng.uniform(*cl['base_rh_pct']), 1),
                'occupancy': round(rng.uniform(*cl['occupancy']), 2),
                'co2_gain_ppm': rng.randint(*cl['co2_gain_ppm']),
            },
        })
    devices += [{'serial_number': serials.next(), 'device_class': 'io_module'}
                for _ in range(rng.randint(*fc['io_modules_per_gateway']))]
    base = gateway_base(cfg, plant_id, gateway_id)
    return {
        'gateway_id': gateway_id,
        'plant_id': plant_id,
        'plant_type': plant_type,
        'family': weighted_choice(rng, fc['gateway_families']),
        'serial_number': serials.next(),
        'lifecycle': 'operational',
        # EICP v1.4: certificate identity == MQTT Client ID == Gateway ID.
        'certificate_cn': gateway_id,
        'client_id': gateway_id,
        'topics': {'d2c': f'{base}/d2c/#', 'c2d': f'{base}/c2d/#'},
        'link': 'flaky' if rng.random() < fc['flaky_link_share'] else 'stable',
        'clock_skew_s': round(rng.uniform(*fc['clock_skew_s']), 3),
        'devices': devices,
    }


def _legacy(cfg):
    legacy = cfg.get('legacy', {})
    out = []
    for gateway_id in legacy.get('gateway_ids', []):
        base = gateway_base(cfg, legacy['plant_id'], gateway_id)
        out.append({
            'gateway_id': gateway_id,
            'plant_id': legacy['plant_id'],
            'profile': 'legacy-aws-iot',
            'lifecycle': 'operational',
            'certificate_subject': legacy['subject'],
            'certificate_cn': None,
            # The certificate carries no Gateway ID; a broker needs a registry lookup.
            'identity_source': 'registry: certificate SHA-256 fingerprint -> Gateway ID',
            'client_id': gateway_id,
            'topics': {'d2c': f'{base}/d2c/#', 'c2d': f'{base}/c2d/#'},
        })
    return out


def bevywise_acl_requests(fleet):
    """Request bodies for the Bevywise/CrystalMQ ACL REST endpoint (/crystalmq/api/v1/acl),
    one per Client ID. Field names as documented by Bevywise; behaviour of the allow lists
    (whitelist only vs. in addition to "allow all") is NOT verified, see brokers/bevywise/README.md."""
    requests = []
    for gw in fleet['gateways'] + fleet.get('legacy_gateways', []):
        requests.append({'clientid': gw['client_id'],
                         'publish_access': 'allow', 'publish_topics': [gw['topics']['d2c']],
                         'subscribe_access': 'allow', 'subscribe_topics': [gw['topics']['c2d']]})
    for svc in fleet['services']:
        requests.append({'clientid': svc['identity'],
                         'publish_access': 'allow', 'publish_topics': svc['write'],
                         'subscribe_access': 'allow', 'subscribe_topics': svc['read']})
    return requests


def render_acl(fleet):
    lines = [
        '# GENERATED by `python -m enetec_sim generate` from sim/config.toml (make fleet).',
        '# Do not edit by hand. Synthetic lab identities only.',
        '# Everything not listed below is denied (Mosquitto acl_file default).',
    ]
    for gw in fleet['gateways']:
        lines += ['', f"user {gw['certificate_cn']}",
                  f"topic write {gw['topics']['d2c']}",
                  f"topic read  {gw['topics']['c2d']}"]
    if fleet.get('legacy_gateways'):
        lines += ['', '# Legacy gateways (certificate without CN): these rules only apply if the broker maps',
                  '# the certificate to the Gateway ID via a registry. With use_identity_as_username',
                  '# (identity = CN) Mosquitto cannot reach them; acceptance cases LEG-* show this.']
        for gw in fleet['legacy_gateways']:
            lines += ['', f"user {gw['gateway_id']}",
                      f"topic write {gw['topics']['d2c']}",
                      f"topic read  {gw['topics']['c2d']}"]
    lines += ['', '# Cloud stand-ins: one direction each, never both.']
    for svc in fleet['services']:
        lines += ['', f"user {svc['identity']}"]
        lines += [f'topic read  {t}' for t in svc['read']]
        lines += [f'topic write {t}' for t in svc['write']]
    return '\n'.join(lines) + '\n'
