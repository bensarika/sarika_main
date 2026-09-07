"""Two readers over one figure: compare, judge each other, iterate once.

A single reader has no way to discover that it misread a figure consistently.
Two independent readers do, but only if each is told whose work it is looking at
and is answered with measurements rather than the other's opinion. This module
holds the decision logic — what disagreement means, which findings survive being
weighed against a reader's own reflection, and whether another pass is warranted
— and takes the run and judge calls as arguments so the policy stays testable
without a model.
"""
import json
from pathlib import Path

SEVERITIES = {'low': 1, 'medium': 2, 'high': 3}
ITERATION_VERDICTS = {'needs_another_pass', 'unusable'}


def _panels(run_dir):
    directory = Path(run_dir) / 'panels'
    return sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []


def _read(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def summarize(run_dir):
    """What a run claims, per panel, small enough to hand to another reader."""
    panels = []
    for panel in _panels(run_dir):
        result = _read(panel / 'result.json', {})
        rows = [r for r in result.get('rows', []) if r.get('status') == 'observed']
        by_series = {}
        for row in rows:
            key = row.get('series_label') or row.get('series_id')
            by_series.setdefault(key, []).append(
                {'x': row.get('x'), 'y': row.get('y')})
        panels.append({'panel': panel.name, 'status': result.get('status'),
                       'counts': result.get('counts', {}),
                       'points_per_series': {k: len(v) for k, v in by_series.items()},
                       'points': by_series})
    return {'run': str(run_dir), 'panels': panels}


def self_reflection(run_dir):
    """What a run said about its own reading, plus what Python measured of it."""
    panels = []
    for panel in _panels(run_dir):
        review = _read(panel / 'review.json', {})
        screen = _read(panel / 'candidate_screen.json', [])
        spacing = _read(panel / 'result.json', {}).get('spacing_check') or {}
        check = review.get('_visual_check') or {}
        panels.append({
            'panel': panel.name,
            'review_status': review.get('status'),
            'spacing': {'missing': spacing.get('missing', 0),
                        'recoverable': spacing.get('recoverable', 0),
                        'per_series': {k: {'kept': v['kept'], 'expected': v['expected']}
                                       for k, v in (spacing.get('series') or {}).items()}},
            'notes': [str(n)[:300] for n in review.get('notes', [])][:20],
            'visual_check': check.get('assessment'),
            'screen': {'checked': len(screen),
                       'failed': sum(1 for s in screen if not s.get('passed')),
                       'corrected': sum(1 for s in screen if s.get('corrected')),
                       'reasons': sorted({s.get('reason') for s in screen
                                          if not s.get('passed') and s.get('reason')})},
        })
    return {'run': str(run_dir), 'panels': panels}


def screen_digest(run_dir, limit=40):
    """The measured pass/fail evidence a judge is shown, bounded in size."""
    digest = []
    for panel in _panels(run_dir):
        for entry in _read(panel / 'candidate_screen.json', [])[:limit]:
            digest.append({'panel': panel.name, 'candidate_id': entry.get('candidate_id'),
                           'series': entry.get('series_id'), 'passed': entry.get('passed'),
                           'reason': entry.get('reason'),
                           'corrected': bool(entry.get('corrected'))})
    return digest


def weigh(judgment, reflection):
    """Cross-judge findings weighed against the judged run's own reflection.

    A finding the run already admits is corroborated and acted on first; a
    finding it contradicts is kept, not dropped, because a reader defending its
    own work is the least reliable witness available.
    """
    admitted = ' '.join(
        [n for panel in reflection.get('panels', []) for n in panel.get('notes', [])]
        + [r for panel in reflection.get('panels', []) for r in panel['screen']['reasons']]
    ).lower()
    weighed = []
    for finding in judgment.get('findings', []):
        issue = str(finding.get('issue', ''))
        words = [w for w in issue.lower().replace('_', ' ').split() if len(w) > 4]
        corroborated = bool(words) and all(w in admitted for w in words)
        weighed.append({**finding,
                        'corroborated_by_self_review': corroborated,
                        'weight': SEVERITIES.get(str(finding.get('severity')), 1)
                        + (1 if corroborated else 0)})
    weighed.sort(key=lambda f: -f['weight'])
    return weighed


def _screen_failed(reflection):
    return any(panel['screen']['failed'] for panel in reflection.get('panels', []))


def _short_of_its_spacing(reflection):
    """Series that kept fewer marks than the rhythm of their own marks implies."""
    return sum(panel.get('spacing', {}).get('missing', 0)
               for panel in reflection.get('panels', []))


def decide(judgment, reflection, comparison, threshold=3):
    """Whether this run earns another pass, and the reasons to hand it."""
    findings = weigh(judgment, reflection)
    reasons = []
    if judgment.get('verdict') in ITERATION_VERDICTS:
        reasons.append({'code': 'cross_judge_' + str(judgment.get('verdict')),
                        'detail': judgment.get('worst_problem') or ''})
    if _screen_failed(reflection):
        reasons.append({'code': 'candidates_failed_the_pixel_screen'})
    missing = _short_of_its_spacing(reflection)
    if missing:
        reasons.append({'code': 'series_shorter_than_their_spacing_implies',
                        'detail': f'{missing} mark(s) unaccounted for between kept points'})
    if any(panel.get('review_status') != 'accepted'
           for panel in reflection.get('panels', [])):
        reasons.append({'code': 'review_not_accepted'})
    for disagreement in (comparison or {}).get('disagreements', []):
        reasons.append({'code': 'cross_run_' + disagreement['code']})
    top = [f for f in findings if f['weight'] >= threshold]
    return {'iterate': bool(reasons and (top or _screen_failed(reflection) or missing)),
            'reasons': reasons, 'findings': findings, 'act_on': top}


def feedback_text(decision, judgment, limit=4000):
    """The correction handed to the next pass, as plain measured statements."""
    lines = ['A previous pass over this same figure was judged by an independent '
             'reader and by Python pixel measurement. Correct these specifically:']
    for finding in decision['act_on'] or decision['findings'][:5]:
        lines.append('- {issue}{series}: {evidence} Fix: {fix}'.format(
            issue=finding.get('issue', 'issue'),
            series=(' (' + str(finding['series']) + ')') if finding.get('series') else '',
            evidence=str(finding.get('evidence', ''))[:400],
            fix=str(finding.get('fix', ''))[:300]))
    for reason in decision['reasons']:
        lines.append('- ' + reason['code'] + (
            ': ' + str(reason['detail'])[:200] if reason.get('detail') else ''))
    if judgment.get('worst_problem'):
        lines.append('Worst problem named by the judge: '
                     + str(judgment['worst_problem'])[:300])
    return '\n'.join(lines)[:limit]


def report(runs, comparison, judgments, decisions, iterations, final_comparison):
    """The whole duel, with disagreement preserved rather than resolved."""
    return {
        'schema_version': 1,
        'runs': runs,
        'first_comparison': comparison,
        'cross_judgments': judgments,
        'decisions': decisions,
        'iterations': iterations,
        'final_comparison': final_comparison,
        'agrees': bool((final_comparison or comparison or {}).get('agrees')),
        'note': ('Each reading was judged by the other provider and by Python pixel '
                 'measurement; agreement between them is evidence for review, not '
                 'proof. Disagreements and screened-out points are kept here.'),
    }
