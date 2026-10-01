"""compare.py with fabricated acceptance reports: no broker needed."""
import tempfile
import unittest
from pathlib import Path

from enetec_sim.acceptance import REQUIREMENTS
from enetec_sim.compare import compare, latest_run, markdown, summary_text
from enetec_sim.config import write_json


def report(profile, verdicts, stamp, label=None, not_run=()):
    reqs = [{'id': rid, 'requirement': text, 'verdict': verdicts.get(rid, 'PASS'), 'advisory': [], 'cases': [rid + 'c']}
            for rid, text in REQUIREMENTS]
    cases = [{'id': r['id'] + 'c', 'requirement': r['id'], 'title': 'case ' + r['id'], 'expected': 'x',
              'mandatory': True, 'verdict': r['verdict'], 'observed': 'obs ' + profile} for r in reqs]
    bad = [r for r in reqs if r['verdict'] != 'PASS']
    counts = {'PASS': len(reqs) - len(bad), 'FAIL': sum(r['verdict'] == 'FAIL' for r in bad),
              'PARTIAL': sum(r['verdict'] == 'PARTIAL' for r in bad), 'INCONCLUSIVE': 0}
    return {'run_id': 'run-' + stamp, 'target': profile, 'profile': profile, 'broker_label': label or profile,
            'broker': 'h:1', 'generated_utc': stamp, 'accepted': not bad, 'mandatory_counts': counts,
            'mandatory_not_run': list(not_run), 'requirements': reqs, 'results': cases,
            'effort': {'R06': 'CUSTOM DEVELOPMENT | ext'} if profile == 'a' else {}}


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.res = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, rep):
        write_json(self.res / name / 'report.json', rep)

    def test_picks_latest_complete_run_per_profile(self):
        self.put('acceptance-1', report('a', {}, '2026-01-01'))
        self.put('acceptance-2', report('a', {'R06': 'FAIL'}, '2026-01-02'))
        self.put('acceptance-3', report('a', {}, '2026-01-03', not_run=['MTLS-01']))  # filtered run: ignored
        path, rep = latest_run('a', self.res)
        self.assertEqual(path.name, 'acceptance-2')

    def test_run_without_evidence_is_skipped(self):
        self.put('acceptance-1', report('a', {}, '2026-01-01'))
        empty = report('a', {}, '2026-01-02')
        empty['mandatory_counts'] = {'PASS': 0, 'FAIL': 0, 'PARTIAL': 0, 'INCONCLUSIVE': 31}  # broker unreachable
        self.put('acceptance-2', empty)
        self.assertEqual(latest_run('a', self.res)[0].name, 'acceptance-1')

    def test_only_evidence_free_runs_name_the_cause(self):
        empty = report('a', {}, '2026-01-02')
        empty['mandatory_counts'] = {'PASS': 0, 'FAIL': 0, 'PARTIAL': 0, 'INCONCLUSIVE': 31}
        self.put('acceptance-2', empty)
        with self.assertRaises(SystemExit) as ctx:
            latest_run('a', self.res)
        self.assertIn('no evidence', str(ctx.exception))
        self.assertIn('not reachable', str(ctx.exception))

    def test_missing_run_explains_what_to_do(self):
        with self.assertRaises(SystemExit) as ctx:
            latest_run('nothing', self.res)
        self.assertIn('make acceptance BROKER=nothing', str(ctx.exception))

    def test_differences_and_statement(self):
        self.put('acceptance-a', report('a', {}, '2026-01-01', label='Broker A'))
        self.put('acceptance-b', report('b', {'R06': 'FAIL', 'R07': 'PARTIAL'}, '2026-01-01', label='Broker B'))
        c = compare('a', 'b', self.res)
        self.assertEqual(c['better_a'], ['R06', 'R07'])
        self.assertEqual(c['better_b'], [])
        self.assertIn('Broker A is closer to acceptance: 0 vs 2', c['statement'])
        self.assertEqual([d['id'] for d in c['differing_cases']], ['R06c', 'R07c'])
        self.assertEqual(c['requirements'][5]['effort_a'], ('CUSTOM DEVELOPMENT', 'ext'))
        self.assertIn('| R06 |', markdown(c))
        self.assertIn('Better in A: R06, R07', summary_text(c))

    def test_shared_limitation_and_equal_brokers(self):
        self.put('acceptance-a', report('a', {'R11': 'FAIL'}, '2026-01-01'))
        self.put('acceptance-b', report('b', {'R11': 'FAIL'}, '2026-01-01'))
        c = compare('a', 'b', self.res)
        self.assertEqual([x['id'] for x in c['shared_limitations']], ['R11c'])
        self.assertTrue(c['statement'].startswith('Both have 1 mandatory'))
        self.assertEqual(c['differing_cases'], [])


if __name__ == '__main__':
    unittest.main()
