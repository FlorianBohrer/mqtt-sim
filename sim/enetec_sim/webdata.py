"""Data for the Baukasten web page (web/baukasten/index.html): make web.

Everything the page shows about brokers comes from files in this repository: the synthetic
fleet, the wire profile, the acceptance case catalogue, the broker profiles and the reference
runs listed in web/baukasten/sources.toml. The JSON is written into index.html between two
markers, so the page works offline (file://) and as one self-contained file.

inject() also embeds the fonts from web/baukasten/fonts as data: URIs (no requests to third
parties) and writes the SHA-256 of the page script into the Content-Security-Policy, so the
browser runs only that exact script. finish() does the same for pages without lab data
(web/erklaerung/index.html). Every edit of a page script needs `make web` afterwards.
"""
import base64
import hashlib
import json
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .acceptance import CASES, LOG_CASES, REQUIREMENTS
from .config import LAB_ROOT, TARGETS_DIR, load_target

WEB_DIR = LAB_ROOT / 'web' / 'baukasten'
EXPLAINER = LAB_ROOT / 'web' / 'erklaerung' / 'index.html'   # interaktive Erklärung, ohne Lab-Daten
DATA_START = '<script id="lab-data" type="application/json">'
DATA_END = '</script>'
FONTS_DIR = WEB_DIR / 'fonts'
FONTS_START = '/* fonts:start'
FONTS_END = '/* fonts:end */'
# (file, family, weight); IBM Plex Sans is a variable font covering 100-700.
FONTS = [('barlow-condensed-600-latin.woff2', 'Barlow Condensed', '600'),
         ('barlow-condensed-700-latin.woff2', 'Barlow Condensed', '700'),
         ('ibm-plex-sans-latin.woff2', 'IBM Plex Sans', '100 700'),
         ('ibm-plex-mono-400-latin.woff2', 'IBM Plex Mono', '400'),
         ('ibm-plex-mono-500-latin.woff2', 'IBM Plex Mono', '500')]
SCRIPT_START = '<script>'
CSP_SCRIPT_SRC = re.compile(r"script-src 'sha256-[A-Za-z0-9+/=_-]+'")
VERDICTS = ('PASS', 'FAIL', 'PARTIAL', 'INCONCLUSIVE')
CASE_ID = re.compile(r'^[A-Z]{2,4}-\d{2}$')


def _cells(line):
    """Cells of a markdown table row; `\\|` inside a cell is a literal pipe."""
    parts = re.split(r'(?<!\\)\|', line.strip())[1:-1]
    return [part.replace('\\|', '|').strip() for part in parts]


def parse_report(path):
    """report.md of the harness: {case: {'v': verdict, 'obs': observation}} from "## Cases",
    plus the cases the run marked as not applicable to its wire profile."""
    text = Path(path).read_text()
    cases, in_table = {}, False
    for line in text.splitlines():
        if line.startswith('## '):
            in_table = line.strip() == '## Cases'
            continue
        if not in_table or not line.startswith('|'):
            continue
        cells = _cells(line)
        if len(cells) != 6 or not CASE_ID.match(cells[0]):
            continue
        verdict = cells[5].strip('*')
        if verdict in VERDICTS:
            cases[cells[0]] = {'v': verdict, 'obs': cells[4]}
    match = re.search(r'Not applicable: (.*)', text)
    for case_id in re.findall(r'\b([A-Z]{2,4}-\d{2}) \(', match.group(1)) if match else []:
        cases[case_id] = {'v': 'N/A', 'obs': 'not applicable to the wire profile of this run'}
    return cases


def parse_summary(path, run_cases):
    """summary.txt / terminal summary: listed cases keep their verdict, every other case the
    run contained passed. No observations in this format."""
    listed, section = {}, None
    for line in Path(path).read_text().splitlines():
        if line.startswith(('Not passed (mandatory):', 'Advisory, not counted:')):
            section = True
            continue
        if section and not line.startswith('  '):
            section = None
        match = re.match(r'\s+([A-Z]{2,4}-\d{2})\s+(PASS|FAIL|PARTIAL|INCONCLUSIVE)\b', line)
        if section and match:
            listed[match.group(1)] = match.group(2)
    unknown = set(listed) - set(run_cases)
    if unknown:
        raise SystemExit(f'{path}: cases {sorted(unknown)} are not in the `cases` list of sources.toml')
    return {case_id: {'v': listed.get(case_id, 'PASS'), 'obs': None} for case_id in run_cases}


def _counts(cases, mandatory_ids):
    counts = {v: 0 for v in VERDICTS}
    for case_id, result in cases.items():
        if case_id in mandatory_ids and result['v'] in counts:
            counts[result['v']] += 1
    return counts


def build(cfg, sources_path=WEB_DIR / 'sources.toml', fleet_path=LAB_ROOT / 'synthetic' / 'fleet.json'):
    sources = tomllib.loads(Path(sources_path).read_text())
    fleet = json.loads(Path(fleet_path).read_text())
    catalogue = [{'id': c.id, 'req': c.requirement, 'mandatory': c.mandatory,
                  'title': c.title['v13'] if isinstance(c.title, dict) else c.title} for c in CASES]
    catalogue += [{'id': case_id, 'req': 'R15', 'mandatory': True, 'title': title}
                  for case_id, title, _ in LOG_CASES]
    catalogue.append({'id': 'LOG-05', 'req': 'R15', 'mandatory': True,
                      'title': 'No private keys or credentials in the broker log or the evidence'})
    mandatory_ids = {c['id'] for c in catalogue if c['mandatory']}

    runs = []
    for run in sources.get('run', []):
        path = LAB_ROOT / run['file']
        if not path.is_file():
            raise SystemExit(f"sources.toml: {run['file']} does not exist")
        cases = parse_report(path) if run['kind'] == 'report' else parse_summary(path, run['cases'])
        counts = _counts(cases, mandatory_ids)
        runs.append({'broker': run['broker'], 'wire': run['wire'], 'date': run['date'], 'kind': run['kind'],
                     'file': run['file'], 'label': run.get('label', ''), 'label_en': run.get('label_en', ''),
                     'cases': cases, 'counts': counts,
                     'mandatory_total': sum(counts.values()),
                     'accepted': sum(counts.values()) > 0 and counts['PASS'] == sum(counts.values())})

    brokers = []
    for key, meta in sources.get('brokers', {}).items():
        facts = []
        for fact in meta.get('facts', []):
            url = fact.get('url', '')
            if not (fact.get('de') and fact.get('en')) or (url and not url.startswith('https://')):
                raise SystemExit(f'sources.toml: brokers.{key}.facts needs de, en and an https:// url (or none)')
            facts.append({'de': fact['de'], 'en': fact['en'], 'url': url})
        path = TARGETS_DIR / f'{key}.toml'
        target = load_target(path) if path.exists() else {}
        brokers.append({'key': key, 'name': meta.get('name', target.get('name', key)), 'name_en': meta.get('name_en', ''),
                        'role': meta.get('role', ''),
                        'role_en': meta.get('role_en', ''), 'note': meta.get('note', ''),
                        'note_en': meta.get('note_en', ''), 'profile_status': target.get('status', 'verified'),
                        'max_packet_bytes': target.get('max_packet_bytes'),
                        'effort': {req: str(value) for req, value in (target.get('effort') or {}).items()},
                        'facts': facts})

    gateways = [{'gateway_id': g['gateway_id'], 'plant_id': g['plant_id'], 'plant_type': g.get('plant_type'),
                 'family': g.get('family'), 'serial': g['serial_number'], 'client_id': g['client_id'],
                 'link': g.get('link'), 'devices': len(g.get('devices', []))} for g in fleet['gateways']]
    legacy = [{'gateway_id': g['gateway_id'], 'plant_id': g['plant_id'], 'serial': g['serial_number'],
               'client_id': g['client_id']} for g in fleet.get('legacy_gateways', [])]
    version = (LAB_ROOT / 'VERSION').read_text().strip() if (LAB_ROOT / 'VERSION').exists() else ''
    return {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'lab_version': version,
        'wire': {'default': cfg['wire']['topics'], 'client_id': cfg['wire']['client_id'],
                 'algorithm': cfg['wire']['client_id_algorithm'],
                 'v13': dict(cfg['topics_v13']), 'lab_eicp': dict(cfg['topics'])},
        'fleet': {'plants': [{'plant_id': p['plant_id'], 'type': p['type']} for p in fleet['plants']],
                  'gateways': gateways, 'legacy': legacy,
                  'legacy_plant': cfg.get('legacy', {}).get('plant_id', 'plt_sim_legacy'),
                  'services': {'ingest': cfg['services']['ingest'], 'command': cfg['services']['command']}},
        'traffic': {'d2c_per_gateway_per_day': cfg['dataset']['d2c_per_gateway_per_day'],
                    'duration_s': cfg['dataset']['duration_s'],
                    'flaky_link_share': cfg['fleet']['flaky_link_share'],
                    'commands_per_gateway_per_h': cfg['commands']['per_gateway_per_h'],
                    'buffer_max_messages': cfg['connectivity']['buffer_max_messages'],
                    'keepalive_s': cfg['mqtt']['keepalive_s'], 'session_expiry_s': cfg['mqtt']['session_expiry_s'],
                    'incidents': [dict(i) for i in cfg['connectivity'].get('incidents', [])]},
        'requirements': [{'id': req_id, 'text': text} for req_id, text in REQUIREMENTS],
        'cases': catalogue,
        'brokers': brokers,
        'runs': runs,
    }


def font_faces(fonts_dir=FONTS_DIR):
    """@font-face rules with the woff2 files as data: URIs."""
    rules = []
    for name, family, weight in FONTS:
        data = base64.b64encode((Path(fonts_dir) / name).read_bytes()).decode('ascii')
        rules.append(f'@font-face {{ font-family: "{family}"; font-style: normal; font-weight: {weight}; '
                     f'font-display: swap; src: url(data:font/woff2;base64,{data}) format("woff2"); }}')
    return '\n'.join(rules)


def script_hash(html):
    """CSP source for the page script: 'sha256-<base64>' of the text between <script> and </script>
    (the one script tag without attributes; data blocks carry id/type and are not executed)."""
    start = 0
    if DATA_START in html:
        start = html.index(DATA_END, html.index(DATA_START) + len(DATA_START)) + len(DATA_END)
    start = html.index(SCRIPT_START, start) + len(SCRIPT_START)
    end = html.index('</script>', start)
    digest = hashlib.sha256(html[start:end].encode('utf-8')).digest()
    return "'sha256-" + base64.b64encode(digest).decode('ascii') + "'"


def inject(data, html_path=WEB_DIR / 'index.html', fonts_dir=FONTS_DIR):
    """Write the lab data, the embedded fonts and the CSP script hash into index.html (idempotent)."""
    html = Path(html_path).read_text()
    start = html.index(DATA_START) + len(DATA_START)
    end = html.index(DATA_END, start)
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    html = html[:start] + payload + html[end:]
    Path(html_path).write_text(finalize(html, html_path, fonts_dir))
    return html_path


def finish(html_path=EXPLAINER, fonts_dir=FONTS_DIR):
    """Fonts and CSP hash for a page without lab data (idempotent)."""
    path = Path(html_path)
    path.write_text(finalize(path.read_text(), path, fonts_dir))
    return path


def finalize(html, html_path, fonts_dir=FONTS_DIR):
    """Embed the fonts between the fonts markers and write the CSP hash of the page script."""
    fstart = html.index('\n', html.index(FONTS_START)) + 1
    fend = html.index(FONTS_END, fstart)
    html = html[:fstart] + font_faces(fonts_dir) + '\n' + html[fend:]
    if not CSP_SCRIPT_SRC.search(html):
        raise SystemExit(f"{html_path}: Content-Security-Policy with script-src 'sha256-...' not found")
    return CSP_SCRIPT_SRC.sub(lambda _: 'script-src ' + script_hash(html), html, count=1)
