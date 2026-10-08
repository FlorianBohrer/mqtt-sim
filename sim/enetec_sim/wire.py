"""Wire profile of the lab: topic layout and how the MQTT Client ID is formed.

Topic profiles
  v13       ENETEC MQTT wire contract v1.3 (06.10.2026, CONFIRMED core proposal, ENTC-61):
            enetec/v1/{clientId}/state  Device -> Cloud, QoS 1, no retain
            enetec/v1/{clientId}/cmd    Cloud -> Device, QoS 1, no retain
  lab-eicp  previous lab fixture (EICP v1.4 summary, 30.09.2026), kept for compatibility runs:
            eicp/v1/sim/{plantId}/gateways/{gatewayId}/d2c|c2d/...

Client ID modes
  derived      Client ID = deterministic pseudonym of the gateway serial (ENTC-47 principle,
               CONFIRMED). The algorithm below is a LAB PLACEHOLDER: the real algorithm,
               its version migration and collision handling are OPEN.
  certificate  Client ID = certificate CN = Gateway ID (LEGACY LAB ASSUMPTION).

Inside the lab "d2c" means Device -> Cloud (v1.3: state) and "c2d" Cloud -> Device (v1.3: cmd).
"""
import hashlib
import os

PRESETS = {
    'v13': {'topics': 'v13', 'client_id': 'derived'},
    'lab-eicp': {'topics': 'lab-eicp', 'client_id': 'certificate'},
}
ALGORITHMS = ('lab-sha256-v0',)


def resolve(cfg):
    """Wire settings from sim/config.toml [wire], overridden by SIM_WIRE=v13|lab-eicp."""
    wire = {'topics': 'v13', 'client_id': 'derived', 'client_id_algorithm': 'lab-sha256-v0'}
    wire.update(cfg.get('wire', {}))
    preset = os.environ.get('SIM_WIRE', '').strip()
    if preset:
        if preset not in PRESETS:
            raise SystemExit(f'SIM_WIRE={preset}: unknown, use one of {", ".join(PRESETS)}')
        wire.update(PRESETS[preset])
    if wire['topics'] not in ('v13', 'lab-eicp'):
        raise SystemExit(f"[wire] topics = {wire['topics']!r}: use v13 or lab-eicp")
    if wire['client_id'] not in ('derived', 'certificate'):
        raise SystemExit(f"[wire] client_id = {wire['client_id']!r}: use derived or certificate")
    if wire['client_id_algorithm'] not in ALGORITHMS:
        raise SystemExit(f"[wire] client_id_algorithm = {wire['client_id_algorithm']!r}: use {ALGORITHMS}")
    wire['label'] = (f"topics {wire['topics']}, client id "
                     + (f"derived ({wire['client_id_algorithm']})" if wire['client_id'] == 'derived'
                        else 'certificate CN'))
    return wire


def derive_client_id(serial, algorithm='lab-sha256-v0'):
    """LAB PLACEHOLDER for the ENTC-47 pseudonym: 'c' + 20 hex digits (21 characters,
    within the 23 characters every MQTT server must accept). Not the ENETEC algorithm."""
    if algorithm != 'lab-sha256-v0':
        raise ValueError(f'unknown client id algorithm {algorithm}')
    return 'c' + hashlib.sha256(f'enetec-lab-v0:{serial}'.encode()).hexdigest()[:20]


def client_id_for(cfg, identity, serial):
    wire = cfg['wire']
    if wire['client_id'] == 'certificate':
        return identity
    return derive_client_id(serial, wire['client_id_algorithm'])


def v13(cfg):
    return cfg['wire']['topics'] == 'v13'


def root(cfg):
    return cfg['topics_v13']['base'] if v13(cfg) else cfg['topics']['base']


def _lab_base(cfg, gw):
    return f"{cfg['topics']['base']}/{gw['plant_id']}/gateways/{gw['gateway_id']}"


def up_topic(cfg, gw, leaf):
    """Device -> Cloud topic of a gateway. v13 has exactly one topic; `leaf` is lab-eicp only."""
    if v13(cfg):
        return f"{root(cfg)}/{gw['client_id']}/{cfg['topics_v13']['state']}"
    return f'{_lab_base(cfg, gw)}/d2c/{leaf}'


def down_topic(cfg, gw, leaf):
    if v13(cfg):
        return f"{root(cfg)}/{gw['client_id']}/{cfg['topics_v13']['cmd']}"
    return f'{_lab_base(cfg, gw)}/c2d/{leaf}'


def up_filter(cfg, gw):
    """What a gateway may publish (its ACL grant)."""
    return up_topic(cfg, gw, None) if v13(cfg) else f'{_lab_base(cfg, gw)}/d2c/#'


def down_filter(cfg, gw):
    """What a gateway may subscribe to (its ACL grant)."""
    return down_topic(cfg, gw, None) if v13(cfg) else f'{_lab_base(cfg, gw)}/c2d/#'


def all_up(cfg):
    """Device -> Cloud traffic of every gateway (cloud ingest)."""
    if v13(cfg):
        return f"{root(cfg)}/+/{cfg['topics_v13']['state']}"
    return f"{cfg['topics']['base']}/+/gateways/+/d2c/#"


def all_down(cfg):
    """Cloud -> Device traffic of every gateway (cloud command service)."""
    if v13(cfg):
        return f"{root(cfg)}/+/{cfg['topics_v13']['cmd']}"
    return f"{cfg['topics']['base']}/+/gateways/+/c2d/#"


def names(cfg):
    """Display names of the two directions."""
    return (cfg['topics_v13']['state'], cfg['topics_v13']['cmd']) if v13(cfg) else ('d2c', 'c2d')
