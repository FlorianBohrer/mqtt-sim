"""Side-by-side comparison of two brokers from their acceptance runs (ENTC-59).

Reads the report.json of the latest complete acceptance run per broker profile (or of
explicit run directories) and states facts only: which requirements differ, which cases
differ, which limitations both share. It does not pick a provider.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import LAB_ROOT, TARGETS_DIR, load_target, write_json

RANK = {'PASS': 0, 'N/A': 0, 'PARTIAL': 1, 'INCONCLUSIVE': 2, 'FAIL': 3}
EFFORT_CLASSES = ('NATIVE', 'CONFIGURATION', 'PLUGIN', 'EXTERNAL SERVICE', 'CUSTOM DEVELOPMENT', 'UNSUPPORTED')


def _rank(verdict):
    return RANK.get(verdict.replace('advisory ', ''), 2)


def _complete(report):
    """A usable run: every mandatory case ran and at least one produced evidence (not only INCONCLUSIVE)."""
    counts = report.get('mandatory_counts', {})
    evidence = counts.get('PASS', 0) + counts.get('FAIL', 0) + counts.get('PARTIAL', 0)
    return not report.get('mandatory_not_run') and evidence > 0


def latest_run(profile, results_dir):
    """Newest complete acceptance report of a broker profile (by profile stem, else by name)."""
    name = None
    path = TARGETS_DIR / f'{profile}.toml'
    if path.exists():
        name = load_target(path).get('name')
    found = []
    for report_path in Path(results_dir).glob('acceptance-*/report.json'):
        try:
            report = json.loads(report_path.read_text())
        except ValueError:
            continue
        if _complete(report) and (report.get('profile') == profile or
                                  (report.get('profile') is None and name and report.get('target') == name)):
            found.append((report.get('generated_utc', ''), report_path.parent, report))
    if not found:
        raise SystemExit(f'No complete acceptance run found for broker "{profile}" in {results_dir}. '
                         f'Run: make acceptance BROKER={profile}   (or make compare ... FRESH=1)')
    found.sort(key=lambda item: item[0])
    return found[-1][1], found[-1][2]


def _parse_effort(report):
    out = {}
    for req, value in (report.get('effort') or {}).items():
        cls, _, note = value.partition('|')
        out[req] = (cls.strip(), note.strip())
    return out


def compare(profile_a, profile_b, results_dir, run_a=None, run_b=None):
    def load(profile, run_dir):
        if run_dir:
            path = Path(run_dir)
            return path, json.loads((path / 'report.json').read_text())
        return latest_run(profile, results_dir)
    dir_a, rep_a = load(profile_a, run_a)
    dir_b, rep_b = load(profile_b, run_b)
    reqs_a = {r['id']: r for r in rep_a['requirements']}
    reqs_b = {r['id']: r for r in rep_b['requirements']}
    cases_a = {r['id']: r for r in rep_a['results']}
    cases_b = {r['id']: r for r in rep_b['results']}
    effort_a, effort_b = _parse_effort(rep_a), _parse_effort(rep_b)

    requirements, better_a, better_b, equal = [], [], [], []
    for req_id in reqs_a:
        va, vb = reqs_a[req_id]['verdict'], reqs_b.get(req_id, {}).get('verdict', 'N/A')
        delta = 'A' if _rank(va) < _rank(vb) else 'B' if _rank(vb) < _rank(va) else '='
        {'A': better_a, 'B': better_b, '=': equal}[delta].append(req_id)
        requirements.append({'id': req_id, 'requirement': reqs_a[req_id]['requirement'], 'a': va, 'b': vb,
                             'better': delta, 'effort_a': effort_a.get(req_id), 'effort_b': effort_b.get(req_id)})
    differing, shared = [], []
    for case_id, ca in cases_a.items():
        cb = cases_b.get(case_id)
        if cb is None:
            continue
        if ca['verdict'] != cb['verdict']:
            differing.append({'id': case_id, 'title': ca['title'], 'mandatory': ca['mandatory'],
                              'a': ca['verdict'], 'b': cb['verdict'],
                              'observed_a': ca['observed'], 'observed_b': cb['observed']})
        elif ca['verdict'] != 'PASS':
            shared.append({'id': case_id, 'title': ca['title'], 'mandatory': ca['mandatory'],
                           'verdict': ca['verdict']})

    def side(profile, run_dir, rep):
        counts = rep['mandatory_counts']
        return {'profile': profile, 'label': rep['broker_label'], 'run': run_dir.name, 'broker': rep['broker'],
                'generated_utc': rep.get('generated_utc'), 'accepted': rep['accepted'], 'counts': counts,
                'mandatory_total': sum(counts.values()),
                'not_passed': counts['FAIL'] + counts['PARTIAL'] + counts['INCONCLUSIVE']}
    a, b = side(profile_a, dir_a, rep_a), side(profile_b, dir_b, rep_b)
    caveats = []
    for s in (a, b):
        target = TARGETS_DIR / f"{s['profile']}.toml"
        if target.exists() and load_target(target).get('status') == 'template':
            caveats.append(f"{s['label']}: profile status 'template' (settings and log patterns not yet confirmed).")
        if s['counts']['INCONCLUSIVE']:
            caveats.append(f"{s['label']}: {s['counts']['INCONCLUSIVE']} inconclusive mandatory case(s), "
                           "no evidence either way.")
    if a['not_passed'] == b['not_passed'] and a['not_passed'] == 0:
        statement = 'Both brokers pass all mandatory cases.'
    elif a['not_passed'] == b['not_passed']:
        statement = f"Both have {a['not_passed']} mandatory case(s) not passed."
    else:
        closer = a if a['not_passed'] < b['not_passed'] else b
        other = b if closer is a else a
        statement = (f"{closer['label']} is closer to acceptance: {closer['not_passed']} vs "
                     f"{other['not_passed']} mandatory case(s) not passed.")
    if not any((effort_a, effort_b)):
        caveats.append('No effort classes (NATIVE/CONFIGURATION/PLUGIN/CUSTOM/UNSUPPORTED) in the profiles.')
    return {'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'a': a, 'b': b, 'statement': statement, 'better_a': better_a, 'better_b': better_b, 'equal': equal,
            'requirements': requirements, 'differing_cases': differing, 'shared_limitations': shared,
            'caveats': caveats}


def _short(label):
    return label if len(label) <= 34 else label[:31] + '...'


def summary_text(c, evidence=None):
    a, b = c['a'], c['b']
    width = 78
    lines = ['=' * width, f"SUMMARY  broker comparison  |  {a['profile']}  vs  {b['profile']}", '=' * width]
    for tag, s in (('A', a), ('B', b)):
        verdict = 'ACCEPTED' if s['accepted'] else 'NOT ACCEPTED'
        lines.append(f"{tag}  {_short(s['label']):34} {verdict:13} "
                     f"{s['mandatory_total'] - s['not_passed']}/{s['mandatory_total']} mandatory PASS")
    lines += ['', c['statement'], '', f"{'':5}{'requirement':50} {'A':9} {'B':9}"]
    for r in c['requirements']:
        mark = {'A': ' <A', 'B': ' B>', '=': ''}[r['better']]
        text = r['requirement'] if len(r['requirement']) <= 48 else r['requirement'][:45] + '...'
        lines.append(f"{r['id']:5}{text:50} {r['a'].replace('advisory ', 'adv '):9} "
                     f"{r['b'].replace('advisory ', 'adv '):9}{mark}")
    lines += ['', f"Better in A: {', '.join(c['better_a']) or '-'}",
              f"Better in B: {', '.join(c['better_b']) or '-'}",
              f"Same result: {len(c['equal'])} of {len(c['requirements'])} requirements"]
    if c['shared_limitations']:
        lines.append('Both fall short on: ' + ', '.join(x['id'] for x in c['shared_limitations']))
    for caveat in c['caveats']:
        lines.append('Note: ' + caveat)
    if evidence:
        lines += ['', f'Details: {evidence}/comparison.md']
    lines.append('=' * width)
    return '\n'.join(lines) + '\n'


def markdown(c):
    a, b = c['a'], c['b']
    esc = lambda text: str(text).replace('|', '\\|')
    lines = [f"# Broker comparison — {a['label']} vs {b['label']}", '',
             f"Generated {c['generated_utc']} from acceptance runs "
             f"A `{a['run']}` ({a['broker']}) and B `{b['run']}` ({b['broker']}).", '',
             f"**{c['statement']}**", '',
             '| | Broker | Result | Mandatory PASS | FAIL | PARTIAL | INCONCLUSIVE |', '|---|---|---|---|---|---|---|']
    for tag, s in (('A', a), ('B', b)):
        n = s['counts']
        lines.append(f"| {tag} | {esc(s['label'])} | {'ACCEPTED' if s['accepted'] else 'NOT ACCEPTED'} | "
                     f"{n['PASS']}/{s['mandatory_total']} | {n['FAIL']} | {n['PARTIAL']} | {n['INCONCLUSIVE']} |")
    lines += ['', '## Requirements', '', '| ID | Requirement | A | B | Better | Effort A | Effort B |',
              '|---|---|---|---|---|---|---|']
    fmt = lambda e: f"{e[0]}: {esc(e[1])}" if e and e[1] else (e[0] if e else '—')
    for r in c['requirements']:
        lines.append(f"| {r['id']} | {esc(r['requirement'])} | **{r['a']}** | **{r['b']}** | "
                     f"{ {'A': 'A', 'B': 'B', '=': '='}[r['better']] } | {fmt(r['effort_a'])} | {fmt(r['effort_b'])} |")
    if c['differing_cases']:
        lines += ['', '## Cases with different results', '',
                  '| Case | Test | A | B | A observed | B observed |', '|---|---|---|---|---|---|']
        for d in c['differing_cases']:
            adv = '' if d['mandatory'] else ' (advisory)'
            lines.append(f"| {d['id']} | {esc(d['title'])}{adv} | **{d['a']}** | **{d['b']}** | "
                         f"{esc(d['observed_a'])[:140]} | {esc(d['observed_b'])[:140]} |")
    if c['shared_limitations']:
        lines += ['', '## Limitations shared by both', '']
        lines += [f"- **{x['id']}** ({x['verdict']}): {x['title']}" for x in c['shared_limitations']]
    if c['caveats']:
        lines += ['', '## Notes', ''] + [f'- {x}' for x in c['caveats']]
    lines += ['', 'Effort classes: ' + ' / '.join(EFFORT_CLASSES) + '. They are the lab assessment recorded in the '
              'broker profiles, based on the observed results. This comparison states facts and does not select '
              'a provider: weights (cost, operations, support, scale) are not part of the acceptance suite.']
    return '\n'.join(lines) + '\n'


def run(profile_a, profile_b, out_dir=None, run_a=None, run_b=None, results_dir=None):
    results_dir = Path(results_dir or LAB_ROOT / 'results')
    c = compare(profile_a, profile_b, results_dir, run_a, run_b)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = Path(out_dir or results_dir / f'compare-{profile_a}-vs-{profile_b}-{stamp}')
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'comparison.json', c)
    (out / 'comparison.md').write_text(markdown(c))
    text = summary_text(c, f'results/{out.name}')
    (out / 'summary.txt').write_text(text)
    return c, text, out
