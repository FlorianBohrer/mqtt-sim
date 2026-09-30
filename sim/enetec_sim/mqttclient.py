"""Shared MQTT 5 / mTLS client setup (paho-mqtt 2.1, as used by test 10)."""
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .config import DEFAULT_CERTS

RUN_PROPERTY = 'sim-run'


@dataclass
class Broker:
    host: str
    port: int
    certs: Path

    @property
    def cafile(self):
        return self.certs / 'ca' / 'ca.crt'

    @classmethod
    def from_env(cls, host=None, port=None, certs=None):
        return cls(host or os.environ.get('SIM_BROKER_HOST', 'localhost'),
                   int(port or os.environ.get('SIM_BROKER_PORT', '8883')),
                   Path(certs or os.environ.get('SIM_CERTS', DEFAULT_CERTS)))


def identity_files(certs, identity):
    """Certificate/key of a fleet identity as created by scripts/02_create_gateway.sh."""
    for group in ('gateways', 'services'):
        folder = certs / group / identity
        if (folder / 'gateway.crt').exists():
            return folder / 'gateway.crt', folder / 'gateway.key'
    raise FileNotFoundError(f'no certificate for {identity} under {certs}; run make fleet')


def new_client(client_id, broker, certfile=None, keyfile=None):
    # No automatic reconnect: every connection attempt is an explicit, logged step.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                         protocol=mqtt.MQTTv5, reconnect_on_failure=False)
    client.connect_timeout = 8
    client.tls_set(ca_certs=str(broker.cafile),
                   certfile=str(certfile) if certfile else None,
                   keyfile=str(keyfile) if keyfile else None)
    return client


def connect_properties(session_expiry_s):
    props = Properties(PacketTypes.CONNECT)
    props.SessionExpiryInterval = session_expiry_s
    return props


def publish_properties(run_id):
    props = Properties(PacketTypes.PUBLISH)
    props.UserProperty = [(RUN_PROPERTY, run_id)]
    return props


def run_of(message):
    props = getattr(message, 'properties', None)
    for key, value in getattr(props, 'UserProperty', None) or []:
        if key == RUN_PROPERTY:
            return value
    return None


def wait_until(predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


class Recorder:
    """Thread-safe evidence log; 'at' is seconds since recorder start (one clock for all actors)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()
        self.events = []

    def now(self):
        return time.perf_counter() - self._t0

    def __call__(self, actor, event, **data):
        record = {'at': round(self.now(), 4), 'actor': actor, 'event': event, **data}
        with self._lock:
            self.events.append(record)
        return record
