"""Synthetic fleet registry: plants, gateways, peripheral devices, service identities."""
import random
import uuid

from . import wire
from .config import parse_utc

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
    pinned, fixed, plant_types = {}, {}, {}
    for entry in fc.get('pinned', []):
        pinned.setdefault(entry['plant_id'], []).append(entry['gateway_id'])
        # Optional (e.g. exported from the Baukasten web page): fixed serial, link, plant type.
        fixed[entry['gateway_id']] = {k: entry[k] for k in ('serial_number', 'link') if k in entry}
        if 'plant_type' in entry:
            plant_types[entry['plant_id']] = entry['plant_type']
    fixed_serials = [str(f['serial_number']) for f in fixed.values() if 'serial_number' in f]
    if len(fixed_serials) != len(set(fixed_serials)):
        raise ValueError('fleet.pinned: serial_number values must be unique')
    serials.used.update(fixed_serials)   # random serials never collide with fixed ones
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
        plant_type = plant_types.get(plant_id, plant_type)   # drawn anyway: same RNG sequence
        ids = pinned.pop(plant_id, [])
        target = max(rng.randint(*fc['gateways_per_plant'][plant_type]), len(ids))
        while len(ids) < target:
            ids.append(f'gw-sim-{next_no:06d}')
            next_no += 1
        gateways += [_gateway(cfg, rng, serials, plant_id, plant_type, gw_id, fixed.get(gw_id, {})) for gw_id in ids]
        plants.append({'plant_id': plant_id, 'type': plant_type, 'gateways': ids})
    if pinned:
        raise ValueError(f'more pinned plants than fleet.plants: {sorted(pinned)}')

    # Cloud stand-ins keep their identity as Client ID (service accounts, not devices).
    services = [
        {'identity': cfg['services']['ingest'], 'client_id': cfg['services']['ingest'],
         'role': 'cloud-ingest (placeholder for the MQTT->Pub/Sub bridge)',
         'read': [wire.all_up(cfg)], 'write': []},
        {'identity': cfg['services']['command'], 'client_id': cfg['services']['command'],
         'role': 'cloud-command (placeholder for the backend command path)',
         'read': [], 'write': [wire.all_down(cfg)]},
    ]
    return {
        'note': 'SYNTHETIC lab fleet generated from sim/config.toml. Not ENETEC data; '
                'message semantics are defined by ENTC-61 (MQTT wire contract v1.3).',
        'generator': {'name': 'enetec_sim', 'seed': cfg['seed'], 'config_sha256': cfg['_sha256']},
        'wire': {k: v for k, v in cfg['wire'].items()},
        'topics': {'up': wire.all_up(cfg), 'down': wire.all_down(cfg), 'root': wire.root(cfg)},
        'plants': plants,
        'gateways': gateways,
        'services': services,
        'legacy_gateways': _legacy(cfg),
    }


def _gateway(cfg, rng, serials, plant_id, plant_type, gateway_id, fixed=None):
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
    fixed = fixed or {}
    family = weighted_choice(rng, fc['gateway_families'])  # RNG order fixed: reproducible fleets
    serial = serials.next()
    serial = str(fixed.get('serial_number', serial))
    gw = {
        'gateway_id': gateway_id,
        'plant_id': plant_id,
        'plant_type': plant_type,
        'family': family,
        'serial_number': serial,
        'lifecycle': 'operational',
        # Lab credential: certificate CN = Gateway ID. The Client ID follows [wire] client_id:
        # derived pseudonym of the serial (ENTC-47) or, legacy, the CN itself.
        'certificate_cn': gateway_id,
        'client_id': wire.client_id_for(cfg, gateway_id, serial),
    }
    link = 'flaky' if rng.random() < fc['flaky_link_share'] else 'stable'   # drawn anyway: same RNG sequence
    if fixed.get('link', link) not in ('stable', 'flaky'):
        raise ValueError(f"fleet.pinned: link of {gateway_id} must be stable or flaky")
    gw.update({
        'topics': {'d2c': wire.up_filter(cfg, gw), 'c2d': wire.down_filter(cfg, gw)},
        'link': fixed.get('link', link),
        'clock_skew_s': round(rng.uniform(*fc['clock_skew_s']), 3),
        'devices': devices,
    })
    return gw


def _legacy(cfg):
    legacy = cfg.get('legacy', {})
    out = []
    for gateway_id in legacy.get('gateway_ids', []):
        gw = {
            'gateway_id': gateway_id,
            'plant_id': legacy['plant_id'],
            'profile': 'legacy-aws-iot',
            'lifecycle': 'operational',
            # The 16-digit ID of the AWS IoT test gateway is its serial.
            'serial_number': gateway_id,
            'certificate_subject': legacy['subject'],
            'certificate_cn': None,
            # The certificate carries no Gateway ID; a broker needs a registry lookup.
            'identity_source': 'registry: certificate SHA-256 fingerprint -> Gateway ID',
            'client_id': wire.client_id_for(cfg, gateway_id, gateway_id),
        }
        gw['topics'] = {'d2c': wire.up_filter(cfg, gw), 'c2d': wire.down_filter(cfg, gw)}
        out.append(gw)
    return out


def render_client_identities(fleet):
    """Registry credential identity -> serial -> authorized Client ID (mqttClientIdentities analogue)."""
    w = fleet['wire']
    lines = ['# GENERATED by `python -m enetec_sim generate` (make fleet). Synthetic lab identities only.',
             f"# Client ID mode: {w['label']}. The derivation is a LAB PLACEHOLDER (ENTC-47: algorithm OPEN).",
             '# identity\tserial\tclient_id\talgorithm']
    algorithm = w['client_id_algorithm'] if w['client_id'] == 'derived' else 'certificate-cn'
    for gw in fleet['gateways'] + fleet.get('legacy_gateways', []):
        lines.append(f"{gw['gateway_id']}\t{gw['serial_number']}\t{gw['client_id']}\t{algorithm}")
    return '\n'.join(lines) + '\n'


def render_emqx_acl(fleet):
    """EMQX 5 file authorization (acl.conf). Identity = certificate CN via
    mqtt.peer_cert_as_username = cn; the final rule denies everything else."""
    def rule(user, action, topics):
        quoted = ', '.join(f'"{t}"' for t in topics)
        return f'{{allow, {{username, "{user}"}}, {action}, [{quoted}]}}.'
    lines = ['%% GENERATED by `python -m enetec_sim generate` from sim/config.toml (make fleet).',
             '%% EMQX 5 file authorization for the ENETEC lab. Synthetic identities only.',
             '%% Username = certificate CN (mqtt.peer_cert_as_username = cn).', '']
    for gw in fleet['gateways'] + fleet.get('legacy_gateways', []):
        lines += [rule(gw['gateway_id'], 'publish', [gw['topics']['d2c']]),
                  rule(gw['gateway_id'], 'subscribe', [gw['topics']['c2d']])]
    lines += ['', '%% Cloud stand-ins: one direction each.']
    for svc in fleet['services']:
        if svc['read']:
            lines.append(rule(svc['identity'], 'subscribe', svc['read']))
        if svc['write']:
            lines.append(rule(svc['identity'], 'publish', svc['write']))
    lines += ['', '%% Deny by default (also set authorization.no_match = deny).', '{deny, all}.']
    return '\n'.join(lines) + '\n'


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
