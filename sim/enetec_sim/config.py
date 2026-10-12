"""Config loading and shared helpers (paths, topics, time formatting)."""
import hashlib
import json
import os
import tomllib
from datetime import datetime, timezone
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = LAB_ROOT / 'sim' / 'config.toml'
# Local overrides, e.g. exported from the Baukasten web page (web/baukasten/). Not committed.
DEFAULT_OVERLAY = LAB_ROOT / 'sim' / 'config.local.toml'
DEFAULT_OUT = LAB_ROOT / 'synthetic'
DEFAULT_ACL = LAB_ROOT / 'mosquitto' / 'config' / 'acl'
EMQX_ACL = LAB_ROOT / 'brokers' / 'emqx' / 'acl.conf'
HIVEMQ_PERMISSIONS = LAB_ROOT / 'brokers' / 'hivemq' / 'permissions.tsv'
DEFAULT_CERTS = LAB_ROOT / 'certs'
TARGETS_DIR = LAB_ROOT / 'sim' / 'targets'
DEFAULT_TARGET = TARGETS_DIR / 'mosquitto-lab.toml'
ACL_TEST_LOCK = LAB_ROOT / 'mosquitto' / 'config' / '.replacement-test-lock'


def _merge(base, extra):
    """Deep merge: tables are merged key by key, everything else (also lists) is replaced."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path=DEFAULT_CONFIG):
    """sim/config.toml, plus sim/config.local.toml if present (only for the default config).
    SIM_CONFIG_OVERLAY=<file> picks another overlay, SIM_CONFIG_OVERLAY=none switches it off."""
    raw = Path(path).read_bytes()
    cfg = tomllib.loads(raw.decode('utf-8'))
    digest = hashlib.sha256(raw)
    overlay = Path(os.environ.get('SIM_CONFIG_OVERLAY') or DEFAULT_OVERLAY)
    if str(overlay) != 'none' and Path(path) == DEFAULT_CONFIG and overlay.is_file():
        extra = overlay.read_bytes()
        _merge(cfg, tomllib.loads(extra.decode('utf-8')))
        digest.update(extra)
        cfg['_overlay'] = str(overlay)
    cfg['_sha256'] = digest.hexdigest()
    from .wire import resolve
    cfg['wire'] = resolve(cfg)   # [wire] of the file, SIM_WIRE overrides
    return cfg


def load_target(path):
    """Broker profile (sim/targets/<broker>.toml): connection, TLS trust, log patterns."""
    path = Path(path)
    if not path.exists() and (TARGETS_DIR / f'{path}.toml').exists():
        path = TARGETS_DIR / f'{path}.toml'  # allow plain profile names, e.g. "emqx"
    return tomllib.loads(path.read_text())


def parse_utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()


def iso_utc(epoch_s):
    return datetime.fromtimestamp(int(epoch_s), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def encode(message):
    """Wire format of a message: compact JSON, as published to the broker."""
    return json.dumps(message, separators=(',', ':')).encode('utf-8')


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        for row in rows:
            f.write(json.dumps(row, separators=(',', ':')) + '\n')


def read_jsonl(path):
    with Path(path).open() as f:
        return [json.loads(line) for line in f if line.strip()]
