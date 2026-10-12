"""Baukasten web page: data generator, config overlay and the export round trip (no browser)."""
import json
import os
import re
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from enetec_sim.config import LAB_ROOT, load_config
from enetec_sim.fleet import build_fleet
from enetec_sim.webdata import (DATA_END, DATA_START, FONTS, WEB_DIR, build, inject, parse_report,
                                parse_summary, script_hash)

REFERENCE = LAB_ROOT / 'docs' / 'mqtt-tests' / 'reference'
FIXTURES = Path(__file__).parent / 'fixtures'


class ParserTest(unittest.TestCase):
    def test_report_cases_observations_and_not_applicable(self):
        cases = parse_report(REFERENCE / '2026-10-08-mosquitto-2.0.18-v13.md')
        self.assertEqual(cases['ID-03']['v'], 'FAIL')
        self.assertIn('CONNACK 0', cases['ID-03']['obs'])
        self.assertEqual(cases['ACL-08']['v'], 'PARTIAL')
        self.assertEqual(cases['PAY-03']['v'], 'N/A')
        self.assertEqual(len(cases), 48)

    def test_summary_lists_failures_and_passes_the_rest(self):
        run_cases = ['MTLS-01', 'MTLS-07', 'MTLS-08', 'ID-01', 'DUP-01', 'LEG-01', 'LEG-02']
        cases = parse_summary(REFERENCE / '2026-10-01-emqx-5.8.6-summary.txt', run_cases)
        self.assertEqual({k: v['v'] for k, v in cases.items()},
                         {'MTLS-01': 'PASS', 'MTLS-07': 'FAIL', 'MTLS-08': 'FAIL', 'ID-01': 'FAIL', 'DUP-01': 'FAIL',
                          'LEG-01': 'FAIL', 'LEG-02': 'PASS'})
        self.assertIsNone(cases['MTLS-01']['obs'])

    def test_summary_case_outside_the_declared_run_is_refused(self):
        with self.assertRaises(SystemExit):
            parse_summary(REFERENCE / '2026-10-01-emqx-5.8.6-summary.txt', ['MTLS-01'])


class PageDataTest(unittest.TestCase):
    def test_build_counts_match_the_reference_reports(self):
        data = build(load_config())
        runs = {(r['broker'], r['wire']): r for r in data['runs']}
        self.assertEqual(runs[('mosquitto-lab', 'v13')]['counts'], {'PASS': 25, 'FAIL': 3, 'PARTIAL': 6, 'INCONCLUSIVE': 0})
        self.assertTrue(runs[('hivemq', 'v13')]['accepted'])
        self.assertEqual(runs[('emqx', 'lab-eicp')]['counts']['PASS'], 29)
        self.assertEqual(sum(c['mandatory'] for c in data['cases']), 34)

    def test_committed_page_carries_current_data(self):
        html = (WEB_DIR / 'index.html').read_text()
        start = html.index(DATA_START) + len(DATA_START)
        page = json.loads(html[start:html.index(DATA_END, start)].replace('<\\/', '</'))
        fresh = build(load_config())
        for data in (page, fresh):
            data.pop('generated_utc')
        self.assertEqual(page, fresh, 'web/baukasten/index.html is stale: run make web and commit the result')

    def test_inject_is_idempotent_and_escapes_script_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            shutil.copy(WEB_DIR / 'index.html', page)
            data = {'note': 'contains </script> on purpose'}
            inject(data, page)
            once = page.read_text()
            inject(data, page)
            self.assertEqual(once, page.read_text())
            self.assertNotIn('contains </script>', once)


class PageSecurityTest(unittest.TestCase):
    """The page runs offline, loads nothing from third parties and runs only its own script."""

    def setUp(self):
        self.html = (WEB_DIR / 'index.html').read_text()
        self.head = self.html[:self.html.index('<style>')]

    def test_csp_allows_only_the_page_script(self):
        csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', self.head)
        self.assertIsNotNone(csp, 'CSP meta tag missing in <head>')
        policy = csp.group(1)
        for directive in ("default-src 'none'", "base-uri 'none'", "form-action 'none'", "object-src 'none'"):
            self.assertIn(directive, policy)
        self.assertIn('script-src ' + script_hash(self.html), policy,
                      'CSP script hash is stale: run make web after editing the page script')
        self.assertNotIn('unsafe-eval', policy)
        self.assertNotRegex(policy, r"script-src[^;]*'unsafe-inline'")

    def test_no_third_party_resources_or_inline_handlers(self):
        markup = re.sub(r'<script\b.*?</script>', '', self.html, flags=re.S)
        self.assertNotRegex(markup, r'<(link|iframe|object|embed|img|form)\b')
        self.assertNotRegex(markup, r'\s(src|href)\s*=\s*["\']?(https?:)?//')
        self.assertNotRegex(markup, r'<[^>]+\son[a-z]+\s*=', 'inline event handler found')
        self.assertNotRegex(self.html, r'url\((["\']?)(https?:)?//')
        self.assertIn('<meta name="referrer" content="no-referrer">', self.head)

    def test_fonts_are_embedded(self):
        faces = re.findall(r'@font-face \{ font-family: "([^"]+)";[^}]*url\(data:font/woff2;base64,', self.html)
        self.assertEqual(len(faces), len(FONTS))
        self.assertTrue((WEB_DIR / 'fonts' / 'OFL-IBM-Plex.txt').is_file())
        self.assertTrue((WEB_DIR / 'fonts' / 'OFL-Barlow.txt').is_file())

    def test_inject_writes_the_hash_of_the_edited_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            page.write_text(self.html.replace('"use strict";', '"use strict"; /* edited */', 1))
            inject({'x': 1}, page)
            html = page.read_text()
            self.assertIn('script-src ' + script_hash(html), html)
            self.assertNotIn('script-src ' + script_hash(self.html), html)


class BilingualTest(unittest.TestCase):
    """German and English texts exist for every case, requirement, broker and run."""

    def test_every_case_and_requirement_has_both_languages(self):
        html = (WEB_DIR / 'index.html').read_text()
        data = build(load_config())
        for table in ('CASE_DE', 'CASE_EN'):
            block = html[html.index(f'const {table} = {{'):]
            block = block[:block.index('\n};')]
            keys = set(re.findall(r'^  "([A-Z]{2,4}-\d{2})": \{', block, flags=re.M))
            self.assertEqual(keys, {c['id'] for c in data['cases']}, table)
        for table in ('REQ_DE', 'REQ_EN'):
            block = html[html.index(f'const {table} = {{'):]
            block = block[:block.index('\n};')]
            self.assertEqual(set(re.findall(r'\b(R\d{2}):', block)), {r['id'] for r in data['requirements']}, table)

    def test_sources_carry_english_texts(self):
        sources = tomllib.loads((WEB_DIR / 'sources.toml').read_text())
        for key, meta in sources['brokers'].items():
            self.assertTrue(meta.get('role_en') and meta.get('note_en'), key)
        for run in sources['run']:
            self.assertTrue(run.get('label_en'), run['file'])


class OverlayAndExportTest(unittest.TestCase):
    def test_overlay_merges_tables_and_replaces_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay = Path(tmp) / 'config.local.toml'
            overlay.write_text('[fleet]\nplants = 2\npinned = [{ gateway_id = "gw-sim-000001", plant_id = "plt_a" }]\n')
            with mock.patch.dict(os.environ, {'SIM_CONFIG_OVERLAY': str(overlay)}):
                cfg = load_config()
            base = load_config()
        self.assertEqual(cfg['fleet']['plants'], 2)
        self.assertEqual(cfg['fleet']['gateway_families'], base['fleet']['gateway_families'])   # merged
        self.assertEqual(len(cfg['fleet']['pinned']), 1)                                       # replaced
        self.assertNotEqual(cfg['_sha256'], base['_sha256'])
        self.assertNotIn('_overlay', base)

    def test_page_export_rebuilds_exactly_the_built_fleet(self):
        # Fixture: what the page exported for a hand-built layout (5 gateways, one with a chosen
        # serial and a flaky link, two legacy gateways) and what the page showed for it.
        with mock.patch.dict(os.environ, {'SIM_CONFIG_OVERLAY': str(FIXTURES / 'baukasten-export.toml')}):
            fleet = build_fleet(load_config())
        expected = json.loads((FIXTURES / 'baukasten-export.expected.json').read_text())
        got = [{'id': g['gateway_id'], 'plant': g['plant_id'], 'serial': g['serial_number'], 'cid': g['client_id'],
                'link': g['link'], 'legacy': False} for g in fleet['gateways']]
        got += [{'id': g['gateway_id'], 'plant': g['plant_id'], 'serial': g['serial_number'], 'cid': g['client_id'],
                 'link': 'stable', 'legacy': True} for g in fleet['legacy_gateways']]
        key = lambda x: x['id']
        self.assertEqual(sorted(got, key=key), sorted(expected, key=key))

    def test_pinned_serials_must_be_unique(self):
        cfg = load_config()
        cfg['fleet']['pinned'] = [{'gateway_id': 'gw-sim-000001', 'plant_id': 'p1', 'serial_number': '7'},
                                  {'gateway_id': 'gw-sim-000002', 'plant_id': 'p1', 'serial_number': '7'}]
        with self.assertRaises(ValueError):
            build_fleet(cfg)


if __name__ == '__main__':
    unittest.main()
