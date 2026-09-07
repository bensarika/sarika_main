"""The same figure, asked of the model with nothing but the question.

Everything else here is scaffolding: measured ticks, detected marks, tools it can
stop and call, screens it must survive. That scaffolding is worth what it adds
over the model working alone, and the only way to know what it adds is to ask the
model alone, on the same page, at the same time. This lane gets one prompt, no
tools, no measurements, no context beyond the image itself, and its answer is
never allowed into the reading - it is kept beside it and compared to it.
"""
import json
import statistics

PROMPT = '''Identify the data represented in this figure and give its coordinates.
Use whatever the image itself tells you - axis labels and ticks, the legend, any
labels printed beside the curves, units, the caption if it is in the image - and
report the data points as values on the figure's own axes, not as pixels.
Return JSON only:
{"x_axis":{"label":"","unit":"","scale":"linear|log"},
 "y_axis":{"label":"","unit":"","scale":"linear|log"},
 "series":[{"label":"as printed","points":[{"x":0,"y":0}]}],
 "notes":[]}
Report the marks that carry data. Do not report error bars, the lines drawn
between marks, or the legend glyphs as data points. If something is unclear,
give your best reading of it and say so in notes rather than leaving it out.'''

SCHEMA = {
    'type': 'object', 'required': ['series'],
    'properties': {
        'x_axis': {'type': 'object'}, 'y_axis': {'type': 'object'},
        'series': {'type': 'array', 'items': {'type': 'object'}},
        'notes': {'type': 'array'}},
    'additionalProperties': True}


def ask(provider, image):
    """One call, one image, no tools and no measurements to lean on."""
    return provider.complete('unsteered', PROMPT, images=[image], schema=SCHEMA)


def points(reading):
    """Every (group, x, y) the answer states, whatever shape it came back in."""
    out = []
    for series in (reading or {}).get('series') or []:
        label = series.get('label') or series.get('id')
        for point in series.get('points') or series.get('seeds') or []:
            try:
                out.append((label, float(point['x']), float(point['y'])))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _span(values):
    return (max(values) - min(values)) if len(values) > 1 else 0.


def compare(reading, rows):
    """How far the unaided answer sits from the reading the harness stands behind.

    Both are in the figure's own units, which differ per axis and per figure, so
    the separation is stated as a share of the span the harness's own kept points
    cover: a dimensionless number that means the same thing on a 0-800 hour axis
    and a 1-1000 ug/mL one. It is reported, never scored - this measures the
    scaffolding, and a threshold here would only hide what it measures.
    """
    alone = points(reading)
    kept = [(r.get('series_label') or r.get('series_id'), r.get('x'), r.get('y'))
            for r in rows or []]
    kept = [(g, float(x), float(y)) for g, x, y in kept
            if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    report = {'points_unaided': len(alone), 'points_kept_by_the_harness': len(kept),
              'groups_unaided': sorted({g for g, _, _ in alone if g}),
              'groups_kept_by_the_harness': sorted({g for g, _, _ in kept if g})}
    report['groups_both_named'] = sorted(
        set(report['groups_unaided']) & set(report['groups_kept_by_the_harness']))
    if not alone or not kept:
        report['reading'] = ('nothing to compare: {a} points unaided, {k} kept'
                             .format(a=len(alone), k=len(kept)))
        return report
    x_span = _span([x for _, x, _ in kept]) or 1.
    y_span = _span([y for _, _, y in kept]) or 1.
    separations = []
    for group, x, y in alone:
        near = [(g, kx, ky) for g, kx, ky in kept if not group or not g or g == group] or kept
        separations.append(min(((x - kx) / x_span) ** 2 + ((y - ky) / y_span) ** 2
                               for _, kx, ky in near) ** .5)
    report['separation_as_a_share_of_the_span'] = {
        'median': round(statistics.median(separations), 4),
        'worst': round(max(separations), 4),
        'x_span': x_span, 'y_span': y_span}
    report['reading'] = (
        'asked with no help the reader gave {a} points in {ga} groups against the '
        'harness\'s {k} in {gk}; each unaided point sits a median {m:.1%} of the '
        'data\'s own span from the nearest kept one'.format(
            a=len(alone), ga=len(report['groups_unaided']) or 'no named',
            k=len(kept), gk=len(report['groups_kept_by_the_harness']) or 'no named',
            m=report['separation_as_a_share_of_the_span']['median']))
    return report


def summary(reading):
    """What the unaided answer said, in one line, for the watcher's feed."""
    named = [s.get('label') or s.get('id') for s in (reading or {}).get('series') or []]
    return ('asked with no help, no tools and no measurements: {n} points in {s} series{names}'
            .format(n=len(points(reading)), s=len(named),
                    names=' (' + ', '.join(str(n) for n in named[:6]) + ')' if named else ''))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))
    return path
