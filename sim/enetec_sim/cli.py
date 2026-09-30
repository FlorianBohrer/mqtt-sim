"""python -m enetec_sim {generate|simulate|verify|acceptance}"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import (DEFAULT_ACL, DEFAULT_CONFIG, DEFAULT_OUT, DEFAULT_TARGET, LAB_ROOT, TARGETS_DIR,
                     load_config, load_target)


def _run_dir(args, prefix):
    if args.run_dir:
        path = Path(args.run_dir)
    else:
        path = LAB_ROOT / 'results' / f"{prefix}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _broker(args):
    from .mqttclient import Broker
    return Broker.resolve(load_target(args.target), args.host, args.port, args.certs)


def cmd_generate(args, cfg):
    from .generate import generate
    fleet, summary = generate(cfg, Path(args.out), None if args.no_acl else Path(args.acl))
    t = summary['telemetry']
    print(f"fleet: {summary['fleet']['plants']} plants, {summary['fleet']['gateways']} gateways, "
          f"{summary['fleet']['devices']} devices -> {args.out}")
    print(f"telemetry: {t['generated']} generated, {t['sent']} sent, {t['buffered_then_sent']} buffered, "
          f"{t['dropped_buffer_overflow']} dropped; {t['per_gateway_per_day']} per gateway/day "
          f"(baseline {t['baseline_per_gateway_per_day']})")
    print(f"commands: {summary['commands']['total']} ({summary['commands']['during_outage']} during outages); "
          f"offline windows: {summary['connectivity']['offline_windows']}")
    if not args.no_acl:
        print(f'ACL written: {args.acl}')
    return 0


def cmd_simulate(args, cfg):
    from .simulate import simulate
    from .verify import verify
    fleet = json.loads((Path(args.out) / 'fleet.json').read_text())
    run_dir = _run_dir(args, 'simulation')
    gateways = args.gateways.split(',') if args.gateways else None
    broker = _broker(args)
    print(f"Broker profile: {load_target(args.target)['name']} at {broker.host}:{broker.port}", flush=True)
    run = simulate(cfg, fleet, Path(args.out) / 'dataset', broker, run_dir, args.speed, gateways)
    report = verify(Path(args.out) / 'dataset', run_dir)
    print((run_dir / 'summary.txt').read_text())
    print(f"Run status: {run['status']}. Evidence: {run_dir}")
    return report['exit']


def cmd_brokers(args, cfg):
    for path in sorted(TARGETS_DIR.glob('*.toml')):
        target = load_target(path)
        print(f"{path.stem:14} {target['name']:32} {target.get('host')}:{target.get('port')}  "
              f"[{target.get('status', 'verified')}]")
    return 0


def cmd_verify(args, cfg):
    from .verify import verify
    report = verify(Path(args.out) / 'dataset', Path(args.run_dir))
    print((Path(args.run_dir) / 'summary.txt').read_text())
    return report['exit']


def cmd_acceptance(args, cfg):
    from .acceptance import report, run_cases
    target = load_target(args.target)
    run_dir = _run_dir(args, 'acceptance')
    if args.phase in ('all', 'run'):
        broker = _broker(args)
        fleet = json.loads((Path(args.out) / 'fleet.json').read_text())
        print(f"ENTC-63 acceptance: {target['name']} at {broker.host}:{broker.port} -> {run_dir}", flush=True)
        only = args.only.split(',') if args.only else None
        run_cases(cfg, fleet, broker, target, run_dir, args.gateway, only)
    if args.phase == 'run':
        return 0
    summary = report(target, run_dir, args.broker_log or os.environ.get('SIM_BROKER_LOG'), args.broker_label)
    print('\n' + (run_dir / 'report.md').read_text())
    print(f"Evidence: {run_dir}\nAcceptance: {'PASS' if summary['accepted'] else 'FAIL'} (exit {summary['exit']})")
    return summary['exit']


def main(argv=None):
    parser = argparse.ArgumentParser(prog='enetec_sim', description=__doc__)
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='synthetic data directory')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('generate', help='fleet, dataset and generated Mosquitto ACL')
    p.add_argument('--acl', default=str(DEFAULT_ACL))
    p.add_argument('--no-acl', action='store_true', help='do not touch the broker ACL')
    p.set_defaults(func=cmd_generate)

    broker_args = argparse.ArgumentParser(add_help=False)
    broker_args.add_argument('--host', help='default: $SIM_BROKER_HOST or localhost')
    broker_args.add_argument('--port', type=int, help='default: $SIM_BROKER_PORT or 8883')
    broker_args.add_argument('--certs', help='default: $SIM_CERTS or <lab>/certs')
    broker_args.add_argument('--run-dir', help='default: results/<kind>-<UTC timestamp>')
    broker_args.add_argument('--target', default=os.environ.get('SIM_TARGET', str(DEFAULT_TARGET)),
                             help='broker profile: file or name in sim/targets/ (e.g. emqx)')

    p = sub.add_parser('simulate', parents=[broker_args], help='replay the dataset, then verify')
    p.add_argument('--speed', type=float, default=720.0, help='time compression (720: 24 h in 2 min)')
    p.add_argument('--gateways', help='comma-separated subset of gateway IDs')
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser('brokers', help='list the broker profiles in sim/targets/')
    p.set_defaults(func=cmd_brokers)

    p = sub.add_parser('verify', help='evaluate an existing simulation run')
    p.add_argument('--run-dir', required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('acceptance', parents=[broker_args],
                       help='ENTC-63 acceptance harness; exit 0 only if all mandatory cases pass')
    p.add_argument('--phase', choices=('all', 'run', 'report'), default='all',
                   help='run = MQTT cases only, report = add broker-log checks and verdict')
    p.add_argument('--broker-log', help='broker log for LOG-* cases (default: $SIM_BROKER_LOG)')
    p.add_argument('--broker-label', help='name/version shown in the report')
    p.add_argument('--only', help='comma-separated case ID prefixes, e.g. MTLS,ACL-1')
    p.add_argument('--gateway', default='gw-sim-000001', help='gateway A = identity of the negative certificates')
    p.set_defaults(func=cmd_acceptance)

    args = parser.parse_args(argv)
    return args.func(args, load_config(args.config))


if __name__ == '__main__':
    sys.exit(main())
