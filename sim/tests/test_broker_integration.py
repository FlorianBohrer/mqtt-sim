"""End-to-end against a real Mosquitto using the lab's own scripts and broker config.

Skipped unless `mosquitto` and `openssl` are on PATH (the sim container has neither;
run locally: cd sim && python3 -m unittest tests.test_broker_integration -v).
"""
import copy
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from enetec_sim.config import DEFAULT_TARGET, LAB_ROOT, load_config
from enetec_sim.generate import generate, write_acls
from enetec_sim.acceptance import load_target, report, run_cases
from enetec_sim.mqttclient import Broker
from enetec_sim.simulate import simulate


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@unittest.skipUnless(shutil.which('mosquitto') and shutil.which('openssl'), 'mosquitto/openssl not installed')
class BrokerIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lab = cls.lab = Path(cls.tmp.name) / 'lab'
        shutil.copytree(LAB_ROOT / 'scripts', lab / 'scripts')
        shutil.copytree(LAB_ROOT / 'mosquitto', lab / 'mosquitto',
                        ignore=shutil.ignore_patterns('.replacement-test-lock'))
        cfg = cls.cfg = copy.deepcopy(load_config())
        cfg['fleet'].update(plants=3)  # plt_sim_002 holds two gateways (B, C)
        cfg['dataset']['duration_s'] = 6 * 3600
        cfg['connectivity']['incidents'] = [
            {'name': 'storm', 'start_s': 3600, 'duration_s': 600, 'share': 1.0}]
        cls.fleet, _ = generate(cfg, lab / 'synthetic', lab / 'mosquitto' / 'config' / 'acl')

        def sh(*args):
            subprocess.run(['sh', *args], cwd=lab, check=True, capture_output=True)
        sh('scripts/01_create_ca_and_broker.sh')
        for gw in cls.fleet['gateways']:
            sh('scripts/02_create_gateway.sh', gw['gateway_id'])
        for svc in cls.fleet['services']:
            sh('scripts/02_create_gateway.sh', svc['identity'], 'services')
        sh('scripts/12_create_negative_identities.sh')
        (lab / 'sim').mkdir()
        shutil.copy(LAB_ROOT / 'sim' / 'config.toml', lab / 'sim' / 'config.toml')
        sh('scripts/15_create_legacy_identities.sh')

        # The lab broker config, only with local paths and a free port.
        port = _free_port()
        conf = (LAB_ROOT / 'mosquitto' / 'config' / 'mosquitto.conf').read_text()
        conf = (conf.replace('listener 8883', f'listener {port}')
                .replace('/mosquitto/certs', str(lab / 'certs'))
                .replace('/mosquitto/config/acl', str(lab / 'mosquitto' / 'config' / 'acl'))
                .replace('/mosquitto/data/', str(lab / 'data') + '/')
                .replace('log_dest stdout', f"log_dest file {lab / 'mosquitto.log'}"))
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            conf += 'user root\n'
        (lab / 'data').mkdir()
        (lab / 'mosquitto.conf').write_text(conf)
        cls.port = port
        cls.start_broker()
        cls.broker = Broker('localhost', port, lab / 'certs')

    @classmethod
    def start_broker(cls):
        cls.proc = subprocess.Popen(['mosquitto', '-c', str(cls.lab / 'mosquitto.conf')],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as s:
                if s.connect_ex(('127.0.0.1', cls.port)) == 0:
                    break
            time.sleep(0.1)

    @classmethod
    def hook_actions(cls):
        """The host side of scripts/13_acceptance.sh for a locally started Mosquitto."""
        acl = cls.lab / 'mosquitto' / 'config' / 'acl'

        def restart(_):
            cls.proc.terminate()   # SIGTERM: Mosquitto writes its persistence file
            cls.proc.wait(10)
            cls.start_broker()

        def revoke(_):
            subprocess.run(['sh', 'scripts/17_revoke_live.sh'], cwd=cls.lab, check=True, capture_output=True)
            cls.proc.send_signal(signal.SIGHUP)

        def withdraw(params):
            write_acls(cls.fleet, acl, withdraw=params['identity'])
            cls.proc.send_signal(signal.SIGHUP)

        def restore(_):
            write_acls(cls.fleet, acl)
            cls.proc.send_signal(signal.SIGHUP)
        return {'restart': restart, 'revoke': revoke, 'acl-withdraw': withdraw, 'acl-restore': restore}

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.tmp.cleanup()

    def test_acceptance_harness(self):
        target = load_target(DEFAULT_TARGET)
        run_dir = self.lab / 'results' / 'acceptance-it'
        runner = HookRunner(run_dir / 'hooks', self.hook_actions())
        runner.start()
        try:
            with mock.patch.dict(os.environ, {'SIM_HOOKS': '1'}):
                run_cases(self.cfg, self.fleet, self.broker, target, run_dir)
        finally:
            runner.stop.set()
            runner.join(5)
        summary = report(target, run_dir, self.lab / 'mosquitto.log', 'integration test')
        verdicts = {r['id']: r['verdict'] for r in summary['results']}
        # Every case must reach a decision; nothing may be inconclusive.
        self.assertNotIn('INCONCLUSIVE', verdicts.values(), summary['results'])
        # Security properties Mosquitto with the lab config does provide.
        for case in ('MTLS-01', 'MTLS-02', 'MTLS-03', 'MTLS-04', 'MTLS-05', 'MTLS-06', 'ID-02',
                     'ACL-01', 'ACL-02', 'ACL-03', 'ACL-04', 'ACL-05', 'ACL-06', 'ACL-07',
                     'QOS-01', 'QOS-02', 'SES-01', 'REC-01', 'LOG-01', 'LOG-02', 'LOG-03', 'LOG-04', 'LOG-05',
                     'PAY-01', 'PAY-02', 'LWT-01', 'LWT-02', 'EXP-01', 'ACL-14'):
            self.assertEqual(verdicts[case], 'PASS', f'{case}: {summary["results"]}')
        # Mosquitto does not bind the Client ID to the certificate (v1.3: derived Client ID).
        for case in ('ID-01', 'ID-03', 'DUP-01'):
            self.assertEqual(verdicts[case], 'FAIL', case)
        # No crlfile in the lab config: the revocation reaches neither the open nor a new connection.
        self.assertEqual(verdicts['REV-01'], 'FAIL')
        # Persistence is on and the session is opened like a gateway's (Clean Start = false): it and the
        # queued command survive the restart (SIGTERM writes the persistence file).
        restart = next(r for r in summary['results'] if r['id'] == 'RST-01')
        self.assertEqual(restart['verdict'], 'PASS', restart)
        self.assertIn('session_present True', restart['observed'])
        self.assertEqual(summary['not_applicable'], {'PAY-03': 'profile sets no max_packet_bytes '
                                                                '(packet limit OPEN, ENTC-61)'})
        # Rotation works with plain mTLS; a CN-less legacy certificate cannot be mapped by Mosquitto.
        for case in ('ROT-01', 'ROT-02', 'LEG-02'):
            self.assertEqual(verdicts[case], 'PASS', f'{case}: {summary["results"]}')
        self.assertEqual(verdicts['LEG-01'], 'FAIL')
        # No unauthorized delivery anywhere (PARTIAL = blocked but not signalled).
        for case in ('ACL-08', 'ACL-09', 'ACL-10', 'ACL-11', 'ACL-12', 'ACL-13'):
            self.assertIn(verdicts[case], ('PASS', 'PARTIAL'), case)
        # Known Mosquitto limitations make the overall verdict fail (exit 1).
        self.assertEqual(summary['exit'], 0 if summary['accepted'] else 1)

    def test_simulation_passes(self):
        run_dir = self.lab / 'results' / 'simulation-it'
        run = simulate(self.cfg, self.fleet, self.lab / 'synthetic' / 'dataset', self.broker, run_dir,
                       speed=1440, drain_s=2)
        self.assertEqual(run['status'], 'completed')
        from enetec_sim.verify import verify
        report = verify(self.lab / 'synthetic' / 'dataset', run_dir)
        self.assertEqual(report['verdict'], 'PASS', report['checks'])
        self.assertGreater(report['c2d']['during_outage_delivered'], 0)


class HookRunner(threading.Thread):
    """Answers the harness hook requests (<run>/hooks/<action>.request) like scripts/13_acceptance.sh."""

    def __init__(self, folder, actions):
        super().__init__(daemon=True)
        self.folder, self.actions, self.stop = folder, actions, threading.Event()

    def run(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        while not self.stop.is_set():
            for request in self.folder.glob('*.request'):
                action = request.name[:-len('.request')]
                params = json.loads(request.read_text() or '{}')
                request.rename(request.with_suffix('.taken'))
                try:
                    self.actions[action](params)
                    answer = 'ok'
                except Exception as exc:  # reported to the case as INCONCLUSIVE
                    answer = f'failed: {exc}'
                (self.folder / f'{action}.done').write_text(answer + '\n')
            time.sleep(0.1)


if __name__ == '__main__':
    unittest.main()
