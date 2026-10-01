"""Evaluate a simulation run against the dataset plan: PASS / FAIL / INCONCLUSIVE.

Evidence is transport level only: a PUBACK or a delivered message proves broker
behaviour, not application processing (MQTT PUBACK != EICP application ACK).
"""
import json
from collections import Counter, defaultdict

from .config import read_jsonl, write_json

EXIT = {'PASS': 0, 'FAIL': 1, 'INCONCLUSIVE': 2}


def _percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, round(pct / 100 * (len(values) - 1)))]


def summary_block(report, run, host, port, evidence):
    """Compact end-of-run summary of a simulation run."""
    d2c, c2d, ses, chk = report['d2c'], report['c2d'], report['sessions'], report['checks']
    width = 74
    failed = [k for k, ok in chk.items() if not ok]
    lines = ['=' * width, f"SUMMARY  architecture simulation  |  {host}:{port}", '=' * width,
             f"Result: {report['verdict']}  (exit {report['exit']})   Run status: {run['status']}",
             f"Run: {report['run_id']}   Gateways: {len(run['gateways'])}   Speed: x{run['speed']:g}", '',
             f"Telemetry d2c   {d2c['received_unique']}/{d2c['expected']} delivered "
             f"({d2c['missing']} missing, {d2c['unexpected']} unexpected), {d2c['duplicates']} QoS-1 duplicates, "
             f"{d2c['buffered_delivered']} sent from offline buffer",
             f"Commands c2d    {c2d['received_unique']}/{c2d['planned']} delivered, "
             f"{c2d['during_outage_delivered']}/{c2d['during_outage_planned']} sent during an outage",
             f"Sessions        {ses['session_present']}/{ses['offline_windows']} resumed after outage, "
             f"{ses['unplanned_disconnects']} unplanned disconnects, {ses['harness_errors']} harness errors",
             f"Latency (ms)    p50 {d2c['latency_ms']['p50']}, p95 {d2c['latency_ms']['p95']}, "
             f"max {d2c['latency_ms']['max']}",
             f"Checks          {len(chk) - len(failed)}/{len(chk)} PASS"
             + (f"   FAILED: {', '.join(failed)}" if failed else '')]
    if run.get('error'):
        lines.append(f"Error: {run['error']}")
    lines += ['', f'Evidence: {evidence}  (report.json, events.jsonl, broker.log)', '=' * width]
    return '\n'.join(lines) + '\n'


def verify(dataset_dir, run_dir):
    run = json.loads((run_dir / 'run.json').read_text())
    events = read_jsonl(run_dir / 'events.jsonl')
    run_id, gateways = run['run_id'], set(run['gateways'])
    plan = [r for r in read_jsonl(dataset_dir / 'telemetry.jsonl') if r['gateway_id'] in gateways]
    commands = {c['message']['messageId']: c
                for c in read_jsonl(dataset_dir / 'commands.jsonl') if c['gateway_id'] in gateways}
    connectivity = json.loads((dataset_dir / 'connectivity.json').read_text())
    by_event = defaultdict(list)
    for e in events:
        by_event[e['event']].append(e)

    # --- d2c telemetry: gateway -> broker -> cloud ingest -------------------
    expected = {r['message']['messageId']: r for r in plan if not r['dropped']}
    receipts = [e for e in by_event['d2c_received'] if e.get('run') == run_id]
    counts = Counter(e['messageId'] for e in receipts)
    missing = sorted(set(expected) - set(counts))
    unexpected = sorted(set(counts) - set(expected))
    mismatch = []
    for e in receipts:
        row = expected.get(e['messageId'])
        parts = e['topic'].split('/')
        if row is None or e['topic'] != row['topic'] or parts[3] != row['plant_id'] \
                or not parts[5] == e['gatewayId'] == row['gateway_id']:
            mismatch.append(e['messageId'])

    publish_at = {}
    for e in by_event['publish']:
        publish_at.setdefault(e['messageId'], e['at'])
    not_published = sorted(set(expected) - set(publish_at))
    pubacks = by_event['puback']
    puback_failed = [e for e in pubacks if e['code'] >= 128]
    acked = {e['messageId'] for e in pubacks if e['code'] < 128}
    unacked = sorted(set(publish_at) - acked)

    first_receipt = {}
    for e in receipts:
        first_receipt.setdefault(e['messageId'], e)
    latency_ms = [round((e['at'] - publish_at[m]) * 1000, 1)
                  for m, e in first_receipt.items() if m in publish_at]
    inversions, last_seq = 0, {}
    for e in sorted(first_receipt.values(), key=lambda x: x['at']):
        if e['seq'] < last_seq.get(e['gatewayId'], 0):
            inversions += 1
        last_seq[e['gatewayId']] = max(e['seq'], last_seq.get(e['gatewayId'], 0))

    # --- c2d commands: cloud -> broker (session queue) -> gateway -----------
    cmd_receipts = [e for e in by_event['c2d_received'] if e.get('run') == run_id]
    cmd_counts = Counter(e['messageId'] for e in cmd_receipts)
    cmd_missing = sorted(set(commands) - set(cmd_counts))
    cmd_wrong = [e['messageId'] for e in cmd_receipts
                 if commands.get(e['messageId'], {}).get('gateway_id') != e['actor']]
    during = [m for m, c in commands.items() if c['during_outage']]

    # --- sessions ------------------------------------------------------------
    windows = sum(len(connectivity[g]) for g in gateways)
    resumes = [e for e in by_event['connack'] if e['actor'] in gateways and e.get('clean_start') is False]
    unplanned = [e for e in by_event['disconnected'] if e.get('expected') is None]
    harness_errors = sum(len(by_event[k]) for k in
                         ('error', 'connect_error', 'reconnect_failed', 'publish_skipped'))

    checks = {
        'run_completed': run['status'] == 'completed',
        'all_planned_published': not not_published,
        'puback_all_success': not puback_failed and not unacked,
        'd2c_complete': not missing,
        'd2c_no_unexpected': not unexpected,
        'd2c_topic_identity_consistent': not mismatch,
        'c2d_complete': not cmd_missing,
        'c2d_only_to_addressed_gateway': not cmd_wrong,
        'session_resumed_after_every_outage': len(resumes) >= windows
                                              and all(e['session_present'] for e in resumes),
        'no_unplanned_disconnects': not unplanned,
    }
    if not checks['run_completed']:
        verdict = 'INCONCLUSIVE'
    else:
        verdict = 'PASS' if all(checks.values()) else 'FAIL'

    report = {
        'run_id': run_id,
        'verdict': verdict,
        'exit': EXIT[verdict],
        'checks': checks,
        'd2c': {
            'planned': len(plan),
            'dropped_by_plan_buffer_overflow': len(plan) - len(expected),
            'expected': len(expected),
            'published': len(publish_at),
            'received_unique': len(counts),
            'missing': len(missing),
            'unexpected': len(unexpected),
            'duplicates': sum(n - 1 for n in counts.values()),
            'dup_flag_received': sum(e['dup'] for e in receipts),
            'inflight_at_drop': sum(len(e.get('inflight', [])) for e in by_event['network_down']),
            'buffered_delivered': sum(expected[m]['buffered'] for m in counts if m in expected),
            'order_inversions': inversions,
            'foreign_run_receipts': len(by_event['d2c_received']) - len(receipts),
            'puback_codes': {str(k): v for k, v in sorted(Counter(e['code'] for e in pubacks).items())},
            'latency_ms': {'p50': _percentile(latency_ms, 50), 'p95': _percentile(latency_ms, 95),
                           'max': max(latency_ms, default=None)},
        },
        'c2d': {
            'planned': len(commands),
            'sent': len(by_event['command_sent']),
            'puback_codes': {str(k): v for k, v in
                             sorted(Counter(e['code'] for e in by_event['command_puback']).items())},
            'received_unique': len(cmd_counts),
            'missing': len(cmd_missing),
            'duplicates': sum(n - 1 for n in cmd_counts.values()),
            'during_outage_planned': len(during),
            'during_outage_delivered': sum(m in cmd_counts for m in during),
            'foreign_run_receipts': len(by_event['c2d_received']) - len(cmd_receipts),
        },
        'sessions': {
            'offline_windows': windows,
            'reconnects_clean_start_false': len(resumes),
            'session_present': sum(e['session_present'] for e in resumes),
            'unplanned_disconnects': len(unplanned),
            'harness_errors': harness_errors,
        },
        'samples': {
            'd2c_missing': missing[:20],
            'd2c_unexpected': unexpected[:20],
            'd2c_identity_mismatch': mismatch[:20],
            'd2c_unacked': unacked[:20],
            'c2d_missing': cmd_missing[:20],
            'unplanned_disconnects': unplanned[:10],
        },
        'note': 'Transport-level evidence only; MQTT PUBACK != EICP application ACK.',
    }
    write_json(run_dir / 'report.json', report)
    lines = [f'verdict: {verdict}'] + [f'check {k}: {"PASS" if v else "FAIL"}' for k, v in checks.items()]
    for section in ('d2c', 'c2d', 'sessions'):
        lines += [f'{section}.{k}: {v}' for k, v in report[section].items()]
    (run_dir / 'summary.txt').write_text('\n'.join(lines) + '\n')
    return report
