"""Weighted decision matrix for the broker selection (ENTC-59): make decide.

Criteria and weights come from sim/decision.toml. Two criteria are taken from lab evidence:
  security_acceptance  latest complete acceptance run of the candidate's broker profile
                       (mandatory cases: PASS = 1, PARTIAL = 0.5, FAIL = 0; INCONCLUSIVE = no evidence)
  development_effort   effort classes [effort] of the broker profile, unless decision.toml
                       gives a sourced score
All other criteria are hand scores (0..5) with a source. A missing score is OPEN, never 0:
a candidate with open weight gets no total, and without complete shortlist candidates the
matrix names no favourite. The matrix does not choose a provider; it makes the choice traceable.
"""
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .compare import latest_run
from .config import LAB_ROOT, TARGETS_DIR, load_target, write_json

DEFAULT_DECISION = LAB_ROOT / 'sim' / 'decision.toml'
EFFORT_SCORE = {'NATIVE': 5, 'CONFIGURATION': 4, 'PLUGIN': 3, 'EXTERNAL SERVICE': 2,
                'CUSTOM DEVELOPMENT': 1, 'UNSUPPORTED': 0}
MAX_INCONCLUSIVE_SHARE = 0.2   # more than this share of mandatory cases without evidence: OPEN
POINTS = {'PASS': 1.0, 'PARTIAL': 0.5, 'FAIL': 0.0}


def load_decision(path=DEFAULT_DECISION):
    data = tomllib.loads(Path(path).read_text())
    weights = data.get('weights', {})
    if not weights or any(not isinstance(w, (int, float)) or w < 0 for w in weights.values()):
        raise SystemExit(f'{path}: [weights] needs non-negative numbers')
    for key, cand in data.get('candidates', {}).items():
        for crit in weights:
            value = cand.get(crit)
            if value is None:
                continue
            if not (isinstance(value, dict) and isinstance(value.get('score'), (int, float))
                    and 0 <= value['score'] <= 5 and str(value.get('source', '')).strip()):
                raise SystemExit(f'{path}: candidates.{key}.{crit} needs {{ score = 0..5, source = "..." }}')
    return data


def security_score(profile, results_dir, wire=None):
    try:
        run_dir, report = latest_run(profile, results_dir, wire)
    except SystemExit:
        return None, f'no usable acceptance run for profile {profile}'
    mandatory = [r for r in report['results'] if r['mandatory']]
    decided = [r for r in mandatory if r['verdict'] in POINTS]
    open_cases = len(mandatory) - len(decided)
    wire = report.get('wire', 'topics lab-eicp, client id certificate CN')
    if not decided or open_cases > MAX_INCONCLUSIVE_SHARE * len(mandatory):
        return None, f'run {run_dir.name}: {open_cases} of {len(mandatory)} mandatory cases inconclusive'
    points = sum(POINTS[r['verdict']] for r in decided)
    counts = report['mandatory_counts']
    note = (f"run {run_dir.name} ({wire}): {counts['PASS']}/{len(mandatory)} PASS, {counts['PARTIAL']} PARTIAL, "
            f"{counts['FAIL']} FAIL, {counts['INCONCLUSIVE']} INCONCLUSIVE")
    if 'topics v13' not in wire:
        note += '; not the v1.3 wire profile'
    return round(5 * points / len(decided), 2), note


def effort_score(profile):
    path = TARGETS_DIR / f'{profile}.toml'
    if not path.exists():
        return None, f'no broker profile {profile}'
    target = load_target(path)
    classes = [str(v).partition('|')[0].strip() for v in (target.get('effort') or {}).values()]
    scores = [EFFORT_SCORE[c] for c in classes if c in EFFORT_SCORE]
    if not scores:
        return None, f'no [effort] classes in sim/targets/{profile}.toml'
    status = target.get('status', 'verified')
    note = f'{len(scores)} requirements classified in sim/targets/{profile}.toml'
    if status != 'verified':
        note += f' (profile status {status})'
    return round(sum(scores) / len(scores), 2), note


def evaluate(decision, results_dir, wire=None):
    weights = decision['weights']
    total_weight = sum(weights.values())
    rows = []
    for key, cand in decision.get('candidates', {}).items():
        profile = cand.get('profile')
        cells = {}
        for crit in weights:
            manual = cand.get(crit)
            if manual is not None:
                cells[crit] = {'score': manual['score'], 'source': manual['source'], 'kind': 'hand'}
                continue
            score, note = None, 'OPEN'
            if crit == 'security_acceptance' and profile:
                score, note = security_score(profile, results_dir, wire)
            elif crit == 'development_effort' and profile:
                score, note = effort_score(profile)
            cells[crit] = {'score': score, 'source': note, 'kind': 'lab' if score is not None else 'open'}
        scored = sum(weights[c] for c, cell in cells.items() if cell['score'] is not None)
        complete = scored == total_weight
        total = (round(sum(weights[c] * (cell['score'] or 0) for c, cell in cells.items()) / total_weight, 2)
                 if complete else None)   # `or 0`: only weight-0 criteria can still be open here
        rows.append({'key': key, 'name': cand.get('name', key), 'profile': profile,
                     'shortlist': bool(cand.get('shortlist', True)), 'cells': cells, 'total': total,
                     'coverage': round(100 * scored / total_weight) if total_weight else 0,
                     'open': [c for c, cell in cells.items() if cell['score'] is None and weights[c] > 0]})
    shortlist = [r for r in rows if r['shortlist']]
    complete = [r for r in shortlist if r['total'] is not None]
    if shortlist and len(complete) == len(shortlist):
        ranking = sorted(complete, key=lambda r: -r['total'])
        statement = f"Highest weighted score on the shortlist: {ranking[0]['name']} ({ranking[0]['total']} of 5)."
        sensitivity = _sensitivity(weights, complete, ranking[0]['key'])
    else:
        ranking, sensitivity = [], []
        missing = '; '.join(f"{r['name']}: {', '.join(r['open'])}" for r in shortlist if r['open'])
        statement = ('No favourite: open criteria on the shortlist (' + missing + ').') if shortlist else \
            'No shortlist candidates in sim/decision.toml.'
    return {'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'weights': weights, 'labels': decision.get('labels', {}), 'rows': rows,
            'ranking': [r['key'] for r in ranking], 'statement': statement, 'sensitivity': sensitivity}


def _sensitivity(weights, rows, leader):
    """Weights whose change by -50 % or +50 % alone changes the leader."""
    flips = []
    for crit in weights:
        for factor in (0.5, 1.5):
            changed = dict(weights, **{crit: weights[crit] * factor})
            total = sum(changed.values())
            best = max(rows, key=lambda r: sum(changed[c] * (r['cells'][c]['score'] or 0) for c in changed) / total)
            if best['key'] != leader:
                flips.append(f"{crit} x{factor}: {best['name']} leads")
    return flips


def _fmt(score):
    return '—' if score is None else f'{score:g}'


def summary_text(d, evidence=None):
    width = 78
    crits = list(d['weights'])
    total_weight = sum(d['weights'].values())
    lines = ['=' * width, 'SUMMARY  broker decision matrix (ENTC-59)', '=' * width,
             'weights: ' + ', '.join(f"{c} {round(100 * w / total_weight)}%" for c, w in d['weights'].items()), '',
             f"{'candidate':34} {'total':>6} {'cover':>6}  " + ' '.join(c[:5] for c in crits)]
    for r in d['rows']:
        name = r['name'] if len(r['name']) <= 33 else r['name'][:30] + '...'
        tag = '' if r['shortlist'] else ' *'
        lines.append(f"{name + tag:34} {_fmt(r['total']):>6} {str(r['coverage']) + '%':>6}  "
                     + ' '.join(f"{_fmt(r['cells'][c]['score']):>5}" for c in crits))
    lines += ['', '* = not on the shortlist (shown for reference, not ranked)', '', d['statement']]
    if d['sensitivity']:
        lines.append('Leader changes if: ' + '; '.join(d['sensitivity']))
    elif d['ranking']:
        lines.append('Leader is stable when any single weight changes by -50 % / +50 %.')
    if evidence:
        lines += ['', f'Details and sources: {evidence}/decision.md']
    lines.append('=' * width)
    return '\n'.join(lines) + '\n'


def markdown(d):
    esc = lambda text: str(text).replace('|', '\\|')
    crits = list(d['weights'])
    total_weight = sum(d['weights'].values())
    lines = ['# Broker decision matrix (ENTC-59)', '', f"Generated {d['generated_utc']}.", '',
             f"**{d['statement']}**", '', '## Weights', '', '| Criterion | Weight |', '|---|---|']
    lines += [f"| {esc(d['labels'].get(c, c))} | {round(100 * d['weights'][c] / total_weight)} % |" for c in crits]
    lines += ['', '## Scores (0..5)', '', '| Candidate | Shortlist | Total | Coverage | '
              + ' | '.join(esc(d['labels'].get(c, c)) for c in crits) + ' |',
              '|---|---|---|---|' + '---|' * len(crits)]
    for r in d['rows']:
        lines.append(f"| {esc(r['name'])} | {'yes' if r['shortlist'] else 'no'} | {_fmt(r['total'])} | "
                     f"{r['coverage']} % | " + ' | '.join(_fmt(r['cells'][c]['score']) for c in crits) + ' |')
    lines += ['', '## Sources', '']
    for r in d['rows']:
        lines.append(f"### {r['name']}")
        lines += [f"- **{esc(d['labels'].get(c, c))}**: {_fmt(r['cells'][c]['score'])} "
                  f"({r['cells'][c]['kind']}) — {esc(r['cells'][c]['source'])}" for c in crits]
        lines.append('')
    if d['sensitivity']:
        lines += ['## Sensitivity', '', 'The leader changes if one weight alone changes by -50 % / +50 %:', '']
        lines += [f'- {x}' for x in d['sensitivity']]
        lines.append('')
    lines += ['Rules: lab = computed from lab evidence (acceptance run, broker profile); hand = scored in '
              'sim/decision.toml with a source; open = no evidence yet, never counted as 0. Total = weighted '
              'mean over all criteria, only when nothing is open. The weights are a proposal (ASSUMPTION) to be '
              'agreed with SOLHEA/ENETEC; this matrix documents the decision basis, it does not select a provider.']
    return '\n'.join(lines) + '\n'


def run(decision_path=DEFAULT_DECISION, results_dir=None, out_dir=None, wire=None):
    results_dir = Path(results_dir or LAB_ROOT / 'results')
    d = evaluate(load_decision(decision_path), results_dir, wire)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = Path(out_dir or results_dir / f'decision-{stamp}')
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'decision.json', d)
    (out / 'decision.md').write_text(markdown(d))
    text = summary_text(d, f'results/{out.name}')
    (out / 'summary.txt').write_text(text)
    return d, text, out
