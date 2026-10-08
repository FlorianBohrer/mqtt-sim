"""Exit semantics of the acceptance report: exit 0 only for a complete, all-PASS run."""
import tempfile
import time
import unittest
from pathlib import Path

from enetec_sim.acceptance import CASES, load_target, report
from enetec_sim.config import DEFAULT_TARGET, write_json

LOG_LINES = [
    "New client connected from 127.0.0.1:1 as gw-sim-000001 (p5, c1, k30, u'gw-sim-000001').",
    'OpenSSL Error[0]: error:0A000086:SSL routines::certificate verify failed',
    "Denied PUBLISH from gw-sim-000001 (d0, q1, r0, m1, 'x', ... (1 bytes))",
    'Client gw-sim-000001 disconnected.',
]


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / 'run'
        self.log = Path(self.tmp.name) / 'broker.log'
        self.now = int(time.time())
        self.log.write_text(''.join(f'{self.now}: {line}\n' for line in LOG_LINES))
        self.target = load_target(DEFAULT_TARGET)

    def tearDown(self):
        self.tmp.cleanup()

    def _results(self, verdicts=None, skip=(), not_applicable=None):
        verdicts, not_applicable = verdicts or {}, not_applicable or {}
        results = [{'id': c.id, 'requirement': c.requirement, 'title': 'x', 'expected': c.expected,
                    'mandatory': c.mandatory, 'verdict': verdicts.get(c.id, 'PASS'), 'observed': 'x'}
                   for c in CASES if c.id not in skip and c.id not in not_applicable]
        write_json(self.run_dir / 'results.json', {
            'run_id': 'run', 'target': 't', 'broker': 'b', 'gateways': {}, 'only': None,
            'wire': 'topics v13, client id derived (lab-sha256-v0)', 'not_applicable': not_applicable,
            'started_epoch': self.now - 1, 'finished_epoch': self.now + 1, 'results': results})

    def test_all_mandatory_pass_exits_zero(self):
        self._results({'MTLS-08': 'FAIL'})  # advisory cases do not block acceptance
        summary = report(self.target, self.run_dir, self.log)
        self.assertTrue(summary['accepted'], summary['requirements'])
        self.assertEqual(summary['exit'], 0)

    def test_any_mandatory_fail_partial_or_inconclusive_exits_one(self):
        for verdict in ('FAIL', 'PARTIAL', 'INCONCLUSIVE'):
            with self.subTest(verdict):
                self._results({'DUP-01': verdict})
                summary = report(self.target, self.run_dir, self.log)
                self.assertEqual(summary['exit'], 1)
                r11 = next(r for r in summary['requirements'] if r['id'] == 'R11')
                self.assertEqual(r11['verdict'], verdict)

    def test_incomplete_run_is_never_accepted(self):
        self._results(skip=('REC-01',))
        summary = report(self.target, self.run_dir, self.log)
        self.assertEqual(summary['mandatory_not_run'], ['REC-01'])
        self.assertEqual(summary['exit'], 1)

    def test_not_applicable_case_does_not_make_the_run_incomplete(self):
        # ID-03 only exists with derived Client IDs; under WIRE=lab-eicp it is N/A, not missing.
        self._results(not_applicable={'ID-03': 'Client ID mode "certificate"'})
        summary = report(self.target, self.run_dir, self.log)
        self.assertEqual(summary['mandatory_not_run'], [])
        self.assertTrue(summary['accepted'])
        self.assertIn('ID-03', summary['not_applicable'])
        self.assertIn('Not applicable', (self.run_dir / 'report.md').read_text())

    def test_new_advisory_cases_do_not_block_acceptance(self):
        self._results({'RST-01': 'FAIL', 'REV-01': 'PARTIAL', 'ACL-14': 'INCONCLUSIVE', 'EXP-01': 'FAIL'})
        summary = report(self.target, self.run_dir, self.log)
        self.assertTrue(summary['accepted'])
        r22 = next(r for r in summary['requirements'] if r['id'] == 'R22')
        self.assertEqual(r22['verdict'], 'advisory FAIL')

    def test_foreign_last_will_blocks_acceptance(self):
        self._results({'LWT-02': 'FAIL'})
        summary = report(self.target, self.run_dir, self.log)
        self.assertFalse(summary['accepted'])
        self.assertEqual(next(r for r in summary['requirements'] if r['id'] == 'R10')['verdict'], 'FAIL')

    def test_missing_broker_log_is_inconclusive(self):
        self._results()
        summary = report(self.target, self.run_dir, None)
        logs = {r['id']: r['verdict'] for r in summary['results'] if r['id'].startswith('LOG')}
        self.assertEqual(set(logs.values()), {'INCONCLUSIVE'})
        self.assertEqual(summary['exit'], 1)

    def test_private_key_in_evidence_fails(self):
        self._results()
        # Assembled at runtime so secret scanners do not flag this fixture.
        (self.run_dir / 'leak.txt').write_text('-----BEGIN EC ' + 'PRIVATE KEY-----\nAAAA\n')
        summary = report(self.target, self.run_dir, self.log)
        log05 = next(r for r in summary['results'] if r['id'] == 'LOG-05')
        self.assertEqual(log05['verdict'], 'FAIL')
        self.assertEqual(summary['exit'], 1)


if __name__ == '__main__':
    unittest.main()
