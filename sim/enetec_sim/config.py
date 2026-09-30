"""Config loading and shared helpers (paths, topics, time formatting)."""
import hashlib
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = LAB_ROOT / 'sim' / 'config.toml'
DEFAULT_OUT = LAB_ROOT / 'synthetic'
DEFAULT_ACL = LAB_ROOT / 'mosquitto' / 'config' / 'acl'
DEFAULT_CERTS = LAB_ROOT / 'certs'
TARGETS_DIR = LAB_ROOT / 'sim' / 'targets'
DEFAULT_TARGET = TARGETS_DIR / 'mosquitto-lab.toml'
ACL_TEST_LOCK = LAB_ROOT / 'mosquitto' / 'config' / '.replacement-test-lock'


def load_config(path=DEFAULT_CONFIG):
    raw = Path(path).read_bytes()
    cfg = tomllib.loads(raw.decode('utf-8'))
    cfg['_sha256'] = hashlib.sha256(raw).hexdigest()
    return cfg


def load_target(path):
    """Broker profile (sim/targets/<broker>.toml): connection, TLS trust, log patterns."""
    path = Path(path)
    if not path.exists() and (TARGETS_DIR / f'{path}.toml').exists():
        path = TARGETS_DIR / f'{path}.toml'  # allow plain profile names, e.g. "emqx"
    return tomllib.loads(path.read_text())


def gateway_base(cfg, plant_id, gateway_id):
    return f"{cfg['topics']['base']}/{plant_id}/gateways/{gateway_id}"


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
