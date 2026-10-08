"""verify.py against fabricated runs: no broker needed."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from enetec_sim.config import load_config, write_json, write_jsonl
from enetec_sim.dataset import build_dataset
from enetec_sim.fleet import build_fleet
from enetec_sim.verify import verify


def small_config():
    cfg = copy.deepcopy(load_config())
    cfg['fleet'].update(plants=2, pinned=cfg['fleet']['pinned'][:1])
    cfg['dataset']['duration_s'] = 7200
    cfg['connectivity']['incidents'] = [
        {'name': 'test-outage', 'start_s': 1800, 'duration_s': 600, 'share': 1.0}]
    return cfg


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.cfg = small_config()
        fleet = build_fleet(self.cfg)
        data = build_dataset(self.cfg, fleet)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.dataset, self.run_dir = root / 'dataset', root / 'run-1'
        write_jsonl(self.dataset / 'telemetry.jsonl', data['telemetry'])
        write_jsonl(self.dataset / 'commands.jsonl', data['commands'])
        write_json(self.dataset / 'connectivity.json', data['connectivity'])
        self.gateways = [g['gateway_id'] for g in fleet['gateways']]
        self.events = self._perfect_run(data)

    def tearDown(self):
        self.tmp.cleanup()

    def _perfect_run(self, data):
        events, at = [], 0.0
        for row in data['telemetry']:
            if row['dropped']:
                continue
            m = row['message']
            at += 0.01
            events.append({'at': at, 'actor': row['gateway_id'], 'event': 'publish', 'mid': 1,
                           'messageId': m['messageId'], 'seq': m['sequenceNumber']})
            events.append({'at': at, 'actor': row['gateway_id'], 'event': 'puback', 'mid': 1, 'code': 0,
                           'messageId': m['messageId']})
            events.append({'at': at + 0.001, 'actor': 'svc-sim-cloud-ingest', 'event': 'd2c_received',
                           'topic': row['topic'], 'messageId': m['messageId'], 'gatewayId': m['gatewayId'],
                           'seq': m['sequenceNumber'], 'dup': False, 'retain': False, 'run': 'run-1'})
        for c in data['commands']:
            events.append({'at': at, 'actor': 'svc-sim-cloud-command', 'event': 'command_sent',
                           'mid': 1, 'messageId': c['message']['messageId']})
            events.append({'at': at, 'actor': c['gateway_id'], 'event': 'c2d_received', 'topic': c['topic'],
                           'messageId': c['message']['messageId'], 'dup': False, 'retain': False,
                           'run': 'run-1'})
        for gid, windows in data['connectivity'].items():
            for _ in windows:
                events.append({'at': at, 'actor': gid, 'event': 'disconnected', 'expected': 'outage'})
                events.append({'at': at, 'actor': gid, 'event': 'connack', 'code': 0,
                               'session_present': True, 'clean_start': False})
        return events

    def _verify(self, events, status='completed'):
        write_json(self.run_dir / 'run.json', {'run_id': 'run-1', 'status': status, 'gateways': self.gateways})
        write_jsonl(self.run_dir / 'events.jsonl', events)
        return verify(self.dataset, self.run_dir)

    def test_perfect_run_passes(self):
        report = self._verify(self.events)
        self.assertEqual(report['verdict'], 'PASS', json.dumps(report['checks']))
        self.assertGreater(report['c2d']['during_outage_delivered'], 0)

    def test_missing_message_fails(self):
        events = [e for e in self.events if e['event'] != 'd2c_received'][:]
        events += [e for e in self.events if e['event'] == 'd2c_received'][1:]
        report = self._verify(events)
        self.assertEqual(report['verdict'], 'FAIL')
        self.assertFalse(report['checks']['d2c_complete'])
        self.assertEqual(report['d2c']['missing'], 1)

    def test_qos1_duplicate_is_reported_not_failed(self):
        dup = dict(next(e for e in self.events if e['event'] == 'd2c_received'), at=999.0)
        report = self._verify(self.events + [dup])
        self.assertEqual(report['verdict'], 'PASS')
        self.assertEqual(report['d2c']['duplicates'], 1)

    def test_foreign_topic_and_lost_session_fail(self):
        events = copy.deepcopy(self.events)
        receipt = next(e for e in events if e['event'] == 'd2c_received')
        receipt['topic'] = 'enetec/v1/c00000000000000000000/state'   # someone else's namespace
        next(e for e in events if e['event'] == 'connack')['session_present'] = False
        report = self._verify(events)
        self.assertFalse(report['checks']['d2c_topic_identity_consistent'])
        self.assertFalse(report['checks']['session_resumed_after_every_outage'])

    def test_stale_messages_from_other_runs_are_ignored(self):
        stale = dict(next(e for e in self.events if e['event'] == 'd2c_received'), run='run-0')
        report = self._verify(self.events + [stale])
        self.assertEqual(report['verdict'], 'PASS')
        self.assertEqual(report['d2c']['foreign_run_receipts'], 1)

    def test_incomplete_run_is_inconclusive(self):
        self.assertEqual(self._verify(self.events, status='incomplete')['verdict'], 'INCONCLUSIVE')


if __name__ == '__main__':
    unittest.main()
