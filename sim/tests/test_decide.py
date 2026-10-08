"""decide.py with fabricated acceptance reports and decision files: no broker needed."""
import tempfile
import unittest
from pathlib import Path

from enetec_sim.config import write_json
from enetec_sim.decide import evaluate, load_decision, markdown, summary_text
from tests.test_compare import report

DECISION = """
[weights]
security_acceptance = 50
operations_ha = 30
cost = 20

[candidates.a]
name = "Broker A"
profile = "a"
operations_ha = { score = 4, source = "SOURCE: test" }
cost = { score = 2, source = "SOURCE: test" }

[candidates.b]
name = "Broker B"
profile = "b"
operations_ha = { score = 3, source = "SOURCE: test" }
cost = { score = 5, source = "SOURCE: test" }

[candidates.ref]
name = "Reference"
profile = "a"
shortlist = false
"""


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.res = self.root / 'results'

    def tearDown(self):
        self.tmp.cleanup()

    def decision(self, text=DECISION):
        path = self.root / 'decision.toml'
        path.write_text(text)
        return load_decision(path)

    def test_open_criterion_is_not_zero_and_names_no_favourite(self):
        write_json(self.res / 'acceptance-a' / 'report.json', report('a', {}, '2026-01-01'))
        d = evaluate(self.decision(), self.res)   # no run for b: its security score is open
        rows = {r['key']: r for r in d['rows']}
        self.assertEqual(rows['a']['cells']['security_acceptance']['score'], 5.0)
        self.assertIsNone(rows['b']['cells']['security_acceptance']['score'])
        self.assertIsNone(rows['b']['total'])
        self.assertEqual(rows['b']['coverage'], 50)
        self.assertEqual(d['ranking'], [])
        self.assertIn('No favourite', d['statement'])
        self.assertIn('Broker B: security_acceptance', d['statement'])

    def test_complete_shortlist_is_ranked_with_sensitivity(self):
        write_json(self.res / 'acceptance-a' / 'report.json', report('a', {}, '2026-01-01'))
        # b: one mandatory FAIL (0 points) and one PARTIAL (0.5 points)
        write_json(self.res / 'acceptance-b' / 'report.json',
                   report('b', {'R06': 'FAIL', 'R07': 'PARTIAL'}, '2026-01-01'))
        d = evaluate(self.decision(), self.res)
        rows = {r['key']: r for r in d['rows']}
        cases = len(report('b', {}, 'x')['results'])
        security_b = round(5 * (cases - 1.5) / cases, 2)
        self.assertEqual(rows['b']['cells']['security_acceptance']['score'], security_b)
        self.assertEqual(rows['a']['total'], round((50 * 5 + 30 * 4 + 20 * 2) / 100, 2))
        self.assertEqual(rows['b']['total'], round((50 * security_b + 30 * 3 + 20 * 5) / 100, 2))
        expected = sorted(['a', 'b'], key=lambda k: -rows[k]['total'])
        self.assertEqual(d['ranking'], expected)   # the reference profile is shown, never ranked
        self.assertIn(f"Highest weighted score on the shortlist: {rows[expected[0]]['name']}", d['statement'])
        # Halving the security weight or raising cost moves the lead: reported, not hidden.
        self.assertTrue(d['sensitivity'])
        self.assertIn('Reference *', summary_text(d))
        self.assertIn('| Broker B | yes |', markdown(d))

    def test_hand_score_needs_range_and_source(self):
        for bad in ('{ score = 7, source = "x" }', '{ score = 3 }', '3'):
            with self.subTest(bad), self.assertRaises(SystemExit):
                self.decision(DECISION.replace('{ score = 4, source = "SOURCE: test" }', bad))

    def test_mostly_inconclusive_run_is_open(self):
        empty = report('a', {}, '2026-01-01')
        for r in empty['results'][:10]:
            r['verdict'] = 'INCONCLUSIVE'
        write_json(self.res / 'acceptance-a' / 'report.json', empty)
        d = evaluate(self.decision(), self.res)
        cell = next(r for r in d['rows'] if r['key'] == 'a')['cells']['security_acceptance']
        self.assertIsNone(cell['score'])
        self.assertIn('inconclusive', cell['source'])


if __name__ == '__main__':
    unittest.main()
