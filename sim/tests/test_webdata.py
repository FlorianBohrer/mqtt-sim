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
from enetec_sim.webdata import (DATA_END, DATA_START, EXPLAINER, FONTS, WEB_DIR, build, finish, inject, parse_report,
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
        self.assertFalse(runs[('mosquitto-lab', 'v13')]['accepted'])
        self.assertEqual({b['key'] for b in data['brokers']}, {'mosquitto-lab', 'emqx', 'cedalo'})
        self.assertFalse(any(r['broker'] == 'cedalo' for r in data['runs']), 'Cedalo has no lab run yet')
        self.assertEqual(runs[('emqx', 'lab-eicp')]['counts']['PASS'], 29)
        # v1.3 runs of 2026-10-13 (Docker lab): RST-01 opens the session like a gateway (Clean Start = false)
        self.assertEqual(runs[('emqx', 'v13')]['counts'], {'PASS': 31, 'FAIL': 3, 'PARTIAL': 0, 'INCONCLUSIVE': 0})
        for key in (('mosquitto-lab', 'v13'), ('emqx', 'v13')):
            self.assertEqual(runs[key]['date'], '2026-10-13', key)
            self.assertEqual(runs[key]['cases']['RST-01']['v'], 'PASS', key)
        self.assertEqual(runs[('emqx', 'v13')]['cases']['EXP-01']['v'], 'FAIL', 'durable sessions deliver expired commands')
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


PAGES = (WEB_DIR / 'index.html', EXPLAINER)


class PageSecurityTest(unittest.TestCase):
    """Both pages (Baukasten, Erklärung) run offline, load nothing from third parties and run
    only their own script."""

    def test_csp_allows_only_the_page_script(self):
        for page in PAGES:
            with self.subTest(page.parent.name):
                html = page.read_text()
                head = html[:html.index('<style>')]
                csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', head)
                self.assertIsNotNone(csp, 'CSP meta tag missing in <head>')
                policy = csp.group(1)
                for directive in ("default-src 'none'", "base-uri 'none'", "form-action 'none'", "object-src 'none'"):
                    self.assertIn(directive, policy)
                self.assertIn('script-src ' + script_hash(html), policy,
                              'CSP script hash is stale: run make web after editing the page script')
                self.assertNotIn('unsafe-eval', policy)
                self.assertNotRegex(policy, r"script-src[^;]*'unsafe-inline'")
                self.assertEqual(html.count('<script>'), 1, 'exactly one executable inline script')
                self.assertIn('<meta name="referrer" content="no-referrer">', head)

    def test_no_third_party_resources_or_inline_handlers(self):
        for page in PAGES:
            with self.subTest(page.parent.name):
                html = page.read_text()
                markup = re.sub(r'<script\b.*?</script>', '', html, flags=re.S)
                self.assertNotRegex(markup, r'<(link|iframe|object|embed|img|form)\b')
                self.assertNotRegex(markup, r'\s(src|href)\s*=\s*["\']?(https?:)?//')
                self.assertNotRegex(markup, r'<[^>]+\son[a-z]+\s*=', 'inline event handler found')
                self.assertNotRegex(html, r'url\((["\']?)(https?:)?//')

    def test_fonts_are_embedded(self):
        for page in PAGES:
            with self.subTest(page.parent.name):
                faces = re.findall(r'@font-face \{ font-family: "([^"]+)";[^}]*url\(data:font/woff2;base64,', page.read_text())
                self.assertEqual(len(faces), len(FONTS))
        self.assertTrue((WEB_DIR / 'fonts' / 'OFL-IBM-Plex.txt').is_file())
        self.assertTrue((WEB_DIR / 'fonts' / 'OFL-Barlow.txt').is_file())

    def test_inject_writes_the_hash_of_the_edited_script(self):
        html_before = (WEB_DIR / 'index.html').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            page.write_text(html_before.replace('"use strict";', '"use strict"; /* edited */', 1))
            inject({'x': 1}, page)
            html = page.read_text()
            self.assertIn('script-src ' + script_hash(html), html)
            self.assertNotIn('script-src ' + script_hash(html_before), html)

    def test_finish_is_idempotent_for_the_explainer(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            shutil.copy(EXPLAINER, page)
            finish(page)
            once = page.read_text()
            finish(page)
            self.assertEqual(once, page.read_text())
            self.assertEqual(once, EXPLAINER.read_text(), 'web/erklaerung/index.html is stale: run make web')

    def test_pages_link_to_each_other(self):
        self.assertIn('href="../erklaerung/index.html"', (WEB_DIR / 'index.html').read_text())
        self.assertIn('href="../baukasten/index.html"', EXPLAINER.read_text())


def explainer():
    html = EXPLAINER.read_text()
    tag = '<script id="stations-data" type="application/json">'
    start = html.index(tag) + len(tag)
    script = html[html.index('<script>'):]
    return json.loads(html[start:html.index('</script>', start)]), html, script


def js_const(script, name):
    """Literal of `const NAME = ...;` from the page script (numbers only, enough for these checks)."""
    return re.search(rf'\b{name} = (\d+)\b', script).group(1)


class ExplainerTest(unittest.TestCase):
    """Interaktive Erklärung: Stationen vollständig in Deutsch und Englisch, echte Lab-Werte,
    Log-Zeilen im Format des Lab-Mosquitto."""

    def test_stations_are_bilingual_and_complete(self):
        stations, _, script = explainer()
        self.assertGreaterEqual(len(stations), 10)
        self.assertEqual(len({s['id'] for s in stations}), len(stations), 'station ids must be unique')
        parts = set(re.findall(r'data-id="(\w+)"', script)) | {f'gw{n}' for n in range(1, 5)}
        only = set(re.findall(r'data-only="(\w+)"', script))
        for s in stations:
            with self.subTest(s['id']):
                for key in ('chapter', 'text'):
                    self.assertTrue(s[key]['de'].strip() and s[key]['en'].strip(), key)
                self.assertIn(s['view'], ('lineup', 'plant'))
                self.assertLessEqual(set(s['focus']), parts, 'focus names a part that is not drawn')
                self.assertLessEqual(set(s.get('only', [])), only)
                self.assertIn(f'case "{s["id"]}":', script, 'station has no "Probiert es aus" block')
        for go in set(re.findall(r'data-go="(\w+)"', script)) | set(re.findall(r'go: "(\w+)"', script)):
            self.assertIn(go, {s['id'] for s in stations}, f'data-go "{go}" names no station')

    def test_real_lab_values(self):
        """Gateways, Client-IDs and ACL lines are those of the committed fleet; timers come from sim/config.toml."""
        stations, _, script = explainer()
        fleet = {g['gateway_id']: g for g in json.loads((LAB_ROOT / 'synthetic' / 'fleet.json').read_text())['gateways']}
        drawn = re.findall(r'\{ id: "([\w-]+)", y: \d+, serial: "(\d+)", cid: "(\w+)" \}', script)
        self.assertEqual(len(drawn), 4)
        for gid, serial, cid in drawn:
            self.assertEqual((fleet[gid]['serial_number'], fleet[gid]['client_id']), (serial, cid), gid)
            self.assertEqual(fleet[gid]['certificate_cn'], gid, 'the page says the certificate carries the gateway ID')
        text = next(s for s in stations if s['id'] == 'clientid')['text']
        for lang in ('de', 'en'):
            self.assertIn(drawn[0][1], text[lang])
            self.assertIn(drawn[0][2], text[lang])
        acl = (LAB_ROOT / 'mosquitto' / 'config' / 'acl').read_text()
        gid, _, cid = drawn[0]
        for line in (f'user {gid}', f'topic write enetec/v1/{cid}/state', f'topic read  enetec/v1/{cid}/cmd',
                     'user svc-sim-cloud-ingest\ntopic read  enetec/v1/+/state',
                     'user svc-sim-cloud-command\ntopic write enetec/v1/+/cmd'):
            self.assertIn(line, acl)
        self.assertIn('topic read  ${topicOf(i, "cmd")}', script, 'ACL lines are rendered like mosquitto/config/acl')
        mqtt = load_config()['mqtt']
        self.assertEqual(int(js_const(script, 'KEEPALIVE_S')), mqtt['keepalive_s'])
        self.assertEqual(int(js_const(script, 'SESSION_EXPIRY_S')), mqtt['session_expiry_s'])

    def test_log_lines_use_the_lab_broker_formats(self):
        """Every non-italic log line is a Mosquitto 2.0.18 line: matched by the lab profile's log patterns,
        or one of the two lines the profile does not need (keep alive timeout, session expiry)."""
        _, _, script = explainer()
        with open(LAB_ROOT / 'sim' / 'targets' / 'mosquitto-lab.toml', 'rb') as fh:
            log = tomllib.load(fh)['log']
        patterns = [log[k] for k in ('connect_accepted', 'auth_failure', 'acl_denied', 'disconnect')]
        patterns += [r'^Client \S+ has exceeded timeout, disconnecting\.$', r'^Expiring client \S+ due to timeout\.$']
        lines = re.findall(r'logReal\(`([^`]+)`\)', script)
        self.assertGreaterEqual(len(lines), 4)
        for template in lines:
            sample = re.sub(r'\$\{[^}]+\}', 'x1', template)
            with self.subTest(template):
                self.assertTrue(any(re.search(p, sample) for p in patterns), sample)


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
