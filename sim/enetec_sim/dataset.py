"""Deterministic D2C/C2D traffic plan for the synthetic fleet.

Times are simulation seconds relative to dataset.start. For every gateway the
plan fixes when the network is down, when the gateway reconnects, which
telemetry is buffered or dropped and when each message is sent. The simulator
replays this plan; verify compares the broker-side observation against it.
"""
import math
import random
from collections import Counter, defaultdict

from .climate import RoomClimate
from .config import encode, gateway_base, iso_utc, parse_utc


def room_devices(gw):
    return [d for d in gw['devices'] if d['device_class'] == 'room_device']


def offline_at(windows, t):
    """Index of the window during which the gateway is offline at t, else None."""
    for i, w in enumerate(windows):
        if w['start'] <= t < w['reconnect']:
            return i
    return None


def build_dataset(cfg, fleet):
    ds = cfg['dataset']
    start = parse_utc(ds['start'])
    gateways = fleet['gateways']
    rooms = sum(len(room_devices(gw)) for gw in gateways)
    # Calibrate so the fleet average matches the planned D2C volume per gateway.
    interval = rooms / len(gateways) * 86400 / ds['d2c_per_gateway_per_day']
    incidents = _incidents(cfg, fleet)

    telemetry, commands, connectivity = [], [], {}
    for gw in gateways:
        gid = gw['gateway_id']
        windows = _windows(cfg, gw, _random_outages(cfg, gw) + incidents.get(gid, []))
        connectivity[gid] = windows
        telemetry += _telemetry(cfg, gw, windows, interval, start)
        commands += _commands(cfg, gw, windows, start)
    telemetry.sort(key=lambda r: (r['created_t'], r['gateway_id'], r['message']['sequenceNumber']))
    commands.sort(key=lambda r: (r['t'], r['gateway_id']))
    return {
        'telemetry': telemetry,
        'commands': commands,
        'connectivity': connectivity,
        'summary': _summary(cfg, fleet, telemetry, commands, connectivity, interval),
    }


def _random_outages(cfg, gw):
    cc, duration = cfg['connectivity'], cfg['dataset']['duration_s']
    rng = random.Random(f"{cfg['seed']}:{gw['gateway_id']}:outages")
    rate = cc['outages_per_h'][gw['link']] / 3600
    lo, hi = cc['outage_duration_s']
    t, out = 0.0, []
    while rate > 0:
        t += rng.expovariate(rate)
        if t >= duration:
            break
        length = math.exp(rng.uniform(math.log(lo), math.log(hi)))
        out.append((t, min(t + length, duration), 'random'))
        t += length
    return out


def _incidents(cfg, fleet):
    duration = cfg['dataset']['duration_s']
    result = {}
    for inc in cfg['connectivity'].get('incidents', []):
        gateways = fleet['gateways']
        if inc.get('select') == 'largest':
            ranked = sorted(gateways, key=lambda g: (-len(room_devices(g)), g['gateway_id']))
            chosen = ranked[:inc.get('count', 1)]
        else:
            rng = random.Random(f"{cfg['seed']}:incident:{inc['name']}")
            count = inc['count'] if 'count' in inc else round(inc['share'] * len(gateways))
            chosen = rng.sample(gateways, count)
        end = min(inc['start_s'] + inc['duration_s'], duration)
        for gw in chosen:
            result.setdefault(gw['gateway_id'], []).append((inc['start_s'], end, inc['name']))
    return result


def _windows(cfg, gw, outages):
    """Merge outages into offline windows: network down at start, back at end,
    gateway connected again at reconnect (end + backoff/jitter)."""
    rng = random.Random(f"{cfg['seed']}:{gw['gateway_id']}:reconnect")
    windows = []
    for start, end, cause in sorted(outages):
        reconnect = end + rng.uniform(*cfg['connectivity']['reconnect_jitter_s'])
        if windows and start <= windows[-1]['reconnect']:
            w = windows[-1]
            w['end'], w['reconnect'] = max(w['end'], end), max(w['reconnect'], reconnect)
            if cause not in w['cause'].split('+'):
                w['cause'] += '+' + cause
        else:
            windows.append({'start': start, 'end': end, 'reconnect': reconnect, 'cause': cause})
    inflight = random.Random(f"{cfg['seed']}:{gw['gateway_id']}:inflight")
    for w in windows:
        for key in ('start', 'end', 'reconnect'):
            w[key] = round(w[key], 3)
        # The simulator moves the drop to right after the last PUBLISH before the
        # window, so that message is still unacknowledged when the link dies.
        w['inflight_drop'] = inflight.random() < cfg['connectivity']['inflight_drop_share']
    return windows


def _telemetry(cfg, gw, windows, interval, start):
    ds, cc, cl = cfg['dataset'], cfg['connectivity'], cfg['climate']
    gid, skew = gw['gateway_id'], gw['clock_skew_s']
    created = []
    for dev in room_devices(gw):
        rng = random.Random(f"{cfg['seed']}:{dev['serial_number']}:telemetry")
        climate = RoomClimate(dev['simulation'], gw['plant_type'], cl['co2_outdoor_ppm'],
                              ds['utc_offset_h'], rng)
        phase = rng.uniform(0, interval)
        k = 0
        while True:
            t = phase + k * interval + rng.uniform(-ds['interval_jitter_s'], ds['interval_jitter_s'])
            k += 1
            if t >= ds['duration_s']:
                break
            if t >= 0:
                created.append((round(t, 3), dev['serial_number'], climate.sample(start + t)))
    created.sort()

    rows, backlog = [], defaultdict(list)
    for seq, (t, serial, values) in enumerate(created, 1):
        row = {'created_t': t, 'window': offline_at(windows, t), 'serial': serial,
               'values': values, 'seq': seq, 'buffered': False, 'dropped': False}
        if row['window'] is not None:
            row['buffered'] = True
            backlog[row['window']].append(row)
        rows.append(row)
    for items in backlog.values():
        # Offline buffer overflow drops the oldest messages first.
        for row in items[:max(len(items) - cc['buffer_max_messages'], 0)]:
            row['dropped'] = True

    gap, last = 1.0 / cc['backlog_flush_per_s'], float('-inf')
    topic = f"{gateway_base(cfg, gw['plant_id'], gid)}/{cfg['topics']['telemetry']}"
    suffix = gid.rsplit('-', 1)[1]
    out = []
    for row in rows:
        send = None
        if not row['dropped']:
            ready = row['created_t'] if row['window'] is None else windows[row['window']]['reconnect']
            send = max(ready, last + gap)
            later = offline_at(windows, send)
            while later is not None:  # queued long enough to run into the next outage
                row['buffered'] = True
                send = max(windows[later]['reconnect'], last + gap)
                later = offline_at(windows, send)
            last = send = round(send, 3)
        out.append({
            't': send,
            'created_t': row['created_t'],
            'gateway_id': gid,
            'plant_id': gw['plant_id'],
            'topic': topic,
            'qos': 1,
            'buffered': row['buffered'],
            'dropped': row['dropped'],
            'message': {
                'messageId': f"sim-msg-{suffix}-{row['seq']:06d}",
                'messageType': 'telemetry.report',
                'schemaVersion': '1.0',
                # Generation time on the gateway clock; buffered data keeps measuredAt.
                'timestamp': int(start + (send if send is not None else row['created_t']) + skew),
                'gatewayId': gid,
                'sequenceNumber': row['seq'],
                'payload': {
                    'deviceId': row['serial'],
                    'measuredAt': iso_utc(start + row['created_t'] + skew),
                    'measurements': row['values'],
                },
            },
        })
    return out


def _commands(cfg, gw, windows, start):
    cc, duration = cfg['commands'], cfg['dataset']['duration_s']
    gid = gw['gateway_id']
    rng = random.Random(f"{cfg['seed']}:{gid}:commands")
    rate, t, times = cc['per_gateway_per_h'] / 3600, 0.0, []
    while rate > 0:
        t += rng.expovariate(rate)
        if t >= duration:
            break
        times.append(t)
    if cc.get('during_outage'):
        times += [(w['start'] + w['reconnect']) / 2 for w in windows]
    topic = f"{gateway_base(cfg, gw['plant_id'], gid)}/{cfg['topics']['command']}"
    suffix = gid.rsplit('-', 1)[1]
    rows = []
    for seq, t in enumerate(sorted(times), 1):
        rows.append({
            't': round(t, 3),
            'gateway_id': gid,
            'plant_id': gw['plant_id'],
            'topic': topic,
            'qos': 1,
            'during_outage': offline_at(windows, t) is not None,
            'message': {
                'messageId': f'sim-cmd-{suffix}-{seq:06d}',
                'messageType': 'simulation.command',
                'schemaVersion': '1.0',
                'timestamp': int(start + t),
                'gatewayId': gid,
                'sequenceNumber': seq,
                'payload': {'purpose': 'synthetic c2d delivery probe; no EICP command semantics'},
            },
        })
    return rows


def _summary(cfg, fleet, telemetry, commands, connectivity, interval):
    duration = cfg['dataset']['duration_s']
    gateways = fleet['gateways']
    sent = [r for r in telemetry if not r['dropped']]
    sizes = [len(encode(r['message'])) for r in sent]
    per_second = Counter(int(r['t']) for r in sent)
    windows = [w for ws in connectivity.values() for w in ws]
    incidents = Counter(c for w in windows for c in w['cause'].split('+') if c != 'random')
    per_gateway = []
    for gw in gateways:
        gid = gw['gateway_id']
        rows = [r for r in telemetry if r['gateway_id'] == gid]
        per_gateway.append({
            'gateway_id': gid, 'plant_id': gw['plant_id'], 'family': gw['family'],
            'link': gw['link'], 'room_devices': len(room_devices(gw)),
            'telemetry': len(rows),
            'buffered': sum(r['buffered'] and not r['dropped'] for r in rows),
            'dropped': sum(r['dropped'] for r in rows),
            'offline_windows': len(connectivity[gid]),
            'commands': sum(c['gateway_id'] == gid for c in commands),
        })
    return {
        'generator': fleet['generator'],
        'window': {'start': cfg['dataset']['start'], 'duration_s': duration},
        'fleet': {
            'plants': len(fleet['plants']),
            'gateways': len(gateways),
            'devices': sum(len(gw['devices']) for gw in gateways),
            'room_devices': sum(len(room_devices(gw)) for gw in gateways),
            'by_family': dict(sorted(Counter(gw['family'] for gw in gateways).items())),
            'by_plant_type': dict(sorted(Counter(p['type'] for p in fleet['plants']).items())),
            'flaky_links': sum(gw['link'] == 'flaky' for gw in gateways),
        },
        'telemetry': {
            'room_report_interval_s': round(interval, 1),
            'generated': len(telemetry),
            'sent': len(sent),
            'buffered_then_sent': sum(r['buffered'] for r in sent),
            'dropped_buffer_overflow': len(telemetry) - len(sent),
            'per_gateway_per_day': round(len(telemetry) / len(gateways) * 86400 / duration, 1),
            'baseline_per_gateway_per_day': cfg['dataset']['d2c_per_gateway_per_day'],
            'payload_bytes_mean': round(sum(sizes) / len(sizes), 1) if sizes else 0,
            'payload_bytes_max': max(sizes, default=0),
            'baseline_payload_bytes_mean': cfg['baseline']['avg_payload_bytes'],
            'baseline_payload_bytes_max': cfg['baseline']['max_payload_bytes'],
            'peak_msgs_per_s': max(per_second.values(), default=0),
        },
        'commands': {
            'total': len(commands),
            'during_outage': sum(c['during_outage'] for c in commands),
        },
        'connectivity': {
            'offline_windows': len(windows),
            'gateways_with_outage': sum(bool(ws) for ws in connectivity.values()),
            'offline_s_total': round(sum(w['reconnect'] - w['start'] for w in windows), 1),
            'inflight_drops': sum(w['inflight_drop'] for w in windows),
            'incident_gateways': dict(sorted(incidents.items())),
        },
        'per_gateway': per_gateway,
    }
