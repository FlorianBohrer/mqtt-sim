"""Replay the synthetic dataset against a real broker.

Actors, each with its own certificate and MQTT 5 connection:
  * one GatewaySim per fleet gateway: publishes d2c telemetry (QoS 1), subscribes
    to its c2d tree, loses the network during planned windows (TCP close without
    MQTT DISCONNECT), buffers, reconnects with Clean Start = false, flushes backlog;
  * CloudIngest: subscribes to all d2c (stand-in for the MQTT->Pub/Sub bridge);
  * CloudCommander: publishes the planned c2d commands, also while gateways are offline.
Every observation goes to events.jsonl; verify.py evaluates it against the plan.
"""
import json
import platform
import random
import socket
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import paho.mqtt
import paho.mqtt.client as mqtt

from .config import encode, read_jsonl, write_json, write_jsonl
from .mqttclient import (Broker, Recorder, connect_properties, identity_files, new_client,
                         publish_properties, run_of, wait_until)


class Clock:
    """Maps simulation seconds of the dataset to wall-clock time (monotonic)."""

    def __init__(self, speed):
        self.speed, self.t0 = speed, None

    def start(self, delay_s=0.5):
        self.t0 = time.monotonic() + delay_s

    def wall(self, t):
        return self.t0 + t / self.speed

    def sim_now(self):
        return None if self.t0 is None else round((time.monotonic() - self.t0) * self.speed, 3)


@dataclass
class Context:
    broker: Broker
    mqtt_cfg: dict
    clock: Clock
    rec: Recorder
    run_id: str
    go: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    abort: threading.Event = field(default_factory=threading.Event)

    def connect(self, client, clean_start):
        client.connect(self.broker.host, self.broker.port, keepalive=self.mqtt_cfg['keepalive_s'],
                       clean_start=clean_start,
                       properties=connect_properties(self.mqtt_cfg['session_expiry_s']))


class GatewaySim(threading.Thread):
    """One gateway, driven by its own thread and paho's manual network loop."""

    def __init__(self, gw, rows, windows, ctx):
        super().__init__(name=gw['gateway_id'], daemon=True)
        self.gw, self.id, self.rows, self.windows, self.ctx = gw, gw['gateway_id'], rows, windows, ctx
        self.client = new_client(self.id, ctx.broker, *identity_files(ctx.broker.certs, self.id))
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.connected, self.connack, self.subacked = False, None, None
        self.session_present, self.clean_start = None, True
        self.closing = None  # why we expect the connection to close: 'outage' | 'shutdown'
        self.inflight = {}
        self.ready, self.done = threading.Event(), threading.Event()
        self.failed = None

    def _log(self, event, **data):
        self.ctx.rec(self.id, event, sim_t=self.ctx.clock.sim_now(), **data)

    def _on_connect(self, client, userdata, flags, reason, props):
        self.connack, self.connected = reason.value, not reason.is_failure
        self.session_present = bool(flags.session_present)
        self._log('connack', code=reason.value, session_present=self.session_present,
                  clean_start=self.clean_start)

    def _on_disconnect(self, client, userdata, flags, reason, props):
        self.connected = False
        self._log('disconnected', code=reason.value, reason=str(reason), expected=self.closing,
                  server_packet=flags.is_disconnect_packet_from_server)

    def _on_publish(self, client, userdata, mid, reason, props):
        self._log('puback', mid=mid, code=reason.value, messageId=self.inflight.pop(mid, None))

    def _on_subscribe(self, client, userdata, mid, reasons, props):
        codes = [r.value for r in reasons]
        self.subacked = all(code < 128 for code in codes)
        self._log('suback', codes=codes)

    def _on_message(self, client, userdata, msg):
        try:
            body = json.loads(msg.payload)
        except ValueError:
            body = {}
        self._log('c2d_received', topic=msg.topic, messageId=body.get('messageId'),
                  dup=bool(msg.dup), retain=bool(msg.retain), run=run_of(msg))

    def _pump(self, until):
        while not self.ctx.abort.is_set():
            remaining = until - time.monotonic()
            if remaining <= 0:
                return
            if self.client.socket() is not None:
                self.client.loop(timeout=min(remaining, 0.05))
            else:
                time.sleep(min(remaining, 0.05))

    def _connect(self, clean_start):
        self.clean_start, self.connack, self.connected = clean_start, None, False
        self._log('connect', clean_start=clean_start)
        try:
            self.ctx.connect(self.client, clean_start)
        except OSError as exc:
            self._log('connect_error', error=f'{type(exc).__name__}: {exc}')
            return False
        deadline = time.monotonic() + 10
        while self.connack is None and self.client.socket() is not None and time.monotonic() < deadline:
            self.client.loop(timeout=0.05)
        return self.connected

    def _subscribe(self):
        self.subacked = None
        self.client.subscribe(self.gw['topics']['c2d'], qos=1)
        deadline = time.monotonic() + 10
        while self.subacked is None and self.connected and time.monotonic() < deadline:
            self.client.loop(timeout=0.05)
        return bool(self.subacked)

    def _reconnect(self):
        # Clean Start = false: resume the session; resubscribe only if it is gone.
        for attempt in range(6):
            if self._connect(clean_start=False):
                if not self.session_present:
                    self._log('session_not_present')
                    self._subscribe()
                return True
            time.sleep(min(0.2 * 2 ** attempt, 5.0) * random.uniform(0.5, 1.0))
        return False

    def _network_down(self, window):
        # Close TCP without an MQTT DISCONNECT, like a lost uplink. The broker
        # keeps the session (Session Expiry) and queues QoS 1 commands.
        self.closing = 'outage'
        self._log('network_down', inflight=sorted(self.inflight.values()),
                  inflight_drop=window.get('inflight_drop', False))
        sock = self.client.socket()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        deadline = time.monotonic() + 3
        while self.client.socket() is not None and time.monotonic() < deadline:
            self.client.loop(timeout=0.05)

    def _network_up(self):
        self.closing = None
        self._log('network_up')
        if not self._reconnect():
            self._log('reconnect_failed')

    def _publish(self, row):
        if not self.connected:
            self._log('unplanned_offline')
            if not self._reconnect():
                self._log('publish_skipped', messageId=row['message']['messageId'])
                return
        info = self.client.publish(row['topic'], encode(row['message']), qos=1, retain=False,
                                   properties=publish_properties(self.ctx.run_id))
        self.inflight[info.mid] = row['message']['messageId']
        self._log('publish', mid=info.mid, rc=int(info.rc), messageId=row['message']['messageId'],
                  seq=row['message']['sequenceNumber'], buffered=row['buffered'], plan_t=row['t'])

    def _down_at(self, i):
        """Planned drop time; for inflight drops right after the last PUBLISH before it."""
        w = self.windows[i]
        if not w.get('inflight_drop'):
            return w['start']
        after = self.windows[i - 1]['reconnect'] if i else float('-inf')
        sends = [r['t'] for r in self.rows if after < r['t'] < w['start']]
        return max(sends) + 1e-6 if sends else w['start']

    def run(self):
        try:
            if not (self._connect(clean_start=True) and self._subscribe()):
                self.failed = 'initial connect/subscribe failed'
                return
            self.ready.set()
            self.ctx.go.wait()
            events = [(self._down_at(i), 0, i, 'down', w) for i, w in enumerate(self.windows)]
            events += [(w['reconnect'], 1, i, 'up', w) for i, w in enumerate(self.windows)]
            events += [(r['t'], 2, i, 'publish', r) for i, r in enumerate(self.rows)]
            for t, _, _, kind, item in sorted(events, key=lambda e: e[:3]):
                self._pump(self.ctx.clock.wall(t))
                if self.ctx.abort.is_set():
                    return
                if kind == 'down':
                    self._network_down(item)
                elif kind == 'up':
                    self._network_up()
                else:
                    self._publish(item)
            deadline = time.monotonic() + 10
            while self.inflight and self.connected and time.monotonic() < deadline:
                self.client.loop(timeout=0.05)
        except Exception as exc:  # recorded as evidence; verify reports the run as incomplete
            self.failed = f'{type(exc).__name__}: {exc}'
            self._log('error', error=self.failed)
        finally:
            self.done.set()
            # Stay online for late commands until the run is stopped.
            while not self.ctx.stop.is_set() and not self.ctx.abort.is_set():
                self._pump(time.monotonic() + 0.1)
            self.closing = 'shutdown'
            if self.connected:
                self.client.disconnect()
                self._pump(time.monotonic() + 0.3)


class CloudClient:
    """Service identity on a paho network thread (loop_start)."""

    def __init__(self, identity, ctx):
        self.id, self.ctx = identity, ctx
        self.client = new_client(identity, ctx.broker, *identity_files(ctx.broker.certs, identity))
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_disconnect = self._on_disconnect
        self.connack, self.subacked, self.closing = None, None, False

    def _on_connect(self, client, userdata, flags, reason, props):
        self.connack = reason.value
        self.ctx.rec(self.id, 'connack', code=reason.value, session_present=bool(flags.session_present))

    def _on_subscribe(self, client, userdata, mid, reasons, props):
        codes = [r.value for r in reasons]
        self.subacked = all(code < 128 for code in codes)
        self.ctx.rec(self.id, 'suback', codes=codes)

    def _on_disconnect(self, client, userdata, flags, reason, props):
        self.ctx.rec(self.id, 'disconnected', code=reason.value, reason=str(reason),
                     expected='shutdown' if self.closing else None)

    def open(self, subscribe=None):
        try:
            self.ctx.connect(self.client, clean_start=True)
        except OSError as exc:
            self.ctx.rec(self.id, 'connect_error', error=f'{type(exc).__name__}: {exc}')
            return False
        self.client.loop_start()
        if not (wait_until(lambda: self.connack is not None, 10) and self.connack == 0):
            return False
        if subscribe:
            self.client.subscribe(subscribe, qos=1)
            return wait_until(lambda: self.subacked is not None, 10) and self.subacked
        return True

    def close(self):
        self.closing = True
        self.client.disconnect()
        self.client.loop_stop()


class CloudIngest(CloudClient):
    def __init__(self, identity, ctx):
        super().__init__(identity, ctx)
        self.client.on_message = self._on_message

    def _on_message(self, client, userdata, msg):
        try:
            body = json.loads(msg.payload)
        except ValueError:
            body = {}
        self.ctx.rec(self.id, 'd2c_received', topic=msg.topic, messageId=body.get('messageId'),
                     gatewayId=body.get('gatewayId'), seq=body.get('sequenceNumber'),
                     dup=bool(msg.dup), retain=bool(msg.retain), run=run_of(msg))


class CloudCommander(CloudClient):
    def __init__(self, identity, rows, ctx):
        super().__init__(identity, ctx)
        self.rows = rows
        self.client.on_publish = self._on_publish
        self.thread = threading.Thread(target=self._run, name=identity, daemon=True)
        # No own lock around publish(): paho calls on_publish while holding its
        # out-message mutex, which publish() also needs.
        self.sent, self.acked = set(), set()

    def _on_publish(self, client, userdata, mid, reason, props):
        self.acked.add(mid)
        self.ctx.rec(self.id, 'command_puback', mid=mid, code=reason.value)

    def _run(self):
        self.ctx.go.wait()
        for row in self.rows:
            while not self.ctx.abort.is_set() and time.monotonic() < self.ctx.clock.wall(row['t']):
                time.sleep(min(self.ctx.clock.wall(row['t']) - time.monotonic(), 0.05))
            if self.ctx.abort.is_set():
                return
            info = self.client.publish(row['topic'], encode(row['message']), qos=1, retain=False,
                                       properties=publish_properties(self.ctx.run_id))
            self.sent.add(info.mid)
            self.ctx.rec(self.id, 'command_sent', mid=info.mid, rc=int(info.rc),
                         messageId=row['message']['messageId'], gatewayId=row['gateway_id'],
                         during_outage=row['during_outage'], sim_t=self.ctx.clock.sim_now())
        wait_until(lambda: self.sent <= self.acked, 10)


def simulate(cfg, fleet, dataset_dir, broker, run_dir, speed, gateway_ids=None, drain_s=5.0):
    run_id = run_dir.name
    ctx = Context(broker, cfg['mqtt'], Clock(speed), Recorder(), run_id)
    wanted = set(gateway_ids or [gw['gateway_id'] for gw in fleet['gateways']])
    gateways = [gw for gw in fleet['gateways'] if gw['gateway_id'] in wanted]
    connectivity = json.loads((dataset_dir / 'connectivity.json').read_text())
    telemetry = defaultdict(list)
    for row in read_jsonl(dataset_dir / 'telemetry.jsonl'):
        if row['gateway_id'] in wanted and not row['dropped']:
            telemetry[row['gateway_id']].append(row)
    commands = [c for c in read_jsonl(dataset_dir / 'commands.jsonl') if c['gateway_id'] in wanted]
    last_t = max([r['t'] for rows in telemetry.values() for r in rows] + [c['t'] for c in commands]
                 + [w['reconnect'] for g in wanted for w in connectivity[g]] + [0])

    run = {'run_id': run_id, 'status': 'setup_failed',
           'started_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'speed': speed, 'broker': {'host': broker.host, 'port': broker.port},
           'gateways': sorted(wanted), 'dataset_window_s': last_t,
           'mqtt': dict(cfg['mqtt'], protocol='5', qos=1),
           'software': {'python': platform.python_version(), 'paho_mqtt': paho.mqtt.__version__}}
    print(f'Run {run_id}: {len(gateways)} gateways, {sum(map(len, telemetry.values()))} telemetry, '
          f'{len(commands)} commands, speed x{speed} (~{last_t / speed:.0f} s)', flush=True)

    ingest = CloudIngest(cfg['services']['ingest'], ctx)
    commander = CloudCommander(cfg['services']['command'], commands, ctx)
    sims = [GatewaySim(gw, telemetry[gw['gateway_id']], connectivity[gw['gateway_id']], ctx)
            for gw in gateways]
    try:
        if not ingest.open(subscribe=f"{cfg['topics']['base']}/+/gateways/+/d2c/#"):
            raise RuntimeError('cloud ingest could not connect/subscribe')
        if not commander.open():
            raise RuntimeError('cloud commander could not connect')
        for sim in sims:
            sim.start()
        for sim in sims:
            if not (sim.ready.wait(20) and not sim.failed):
                raise RuntimeError(f'{sim.id}: {sim.failed or "not ready"}')
        ctx.clock.start()
        ctx.go.set()
        commander.thread.start()
        run['status'] = 'running'
        deadline = ctx.clock.wall(last_t) + 60
        while not all(s.done.is_set() for s in sims) and time.monotonic() < deadline:
            time.sleep(1)
            sim_t = ctx.clock.sim_now()
            if int(sim_t / speed) % 10 == 0:
                sent = sum(e['event'] == 'publish' for e in ctx.rec.events)
                print(f'  t={max(sim_t, 0):8.0f}s / {last_t:.0f}s  published={sent}', flush=True)
        commander.thread.join(max(deadline - time.monotonic(), 1))
        time.sleep(drain_s)  # late PUBACKs and queued commands after the last reconnect
        failed = [s.id for s in sims if s.failed]
        run['status'] = 'completed' if all(s.done.is_set() for s in sims) and not failed else 'incomplete'
        run['failed_gateways'] = failed
    except RuntimeError as exc:
        run['error'] = str(exc)
        ctx.abort.set()
        print(f'ERROR: {exc}', flush=True)
    finally:
        ctx.stop.set()
        for sim in sims:
            if sim.is_alive():
                sim.join(10)
        commander.close()
        ingest.close()
        run['finished_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        write_jsonl(run_dir / 'events.jsonl', ctx.rec.events)
        write_json(run_dir / 'run.json', run)
    return run
