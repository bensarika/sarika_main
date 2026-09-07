"""Score the deterministic half of the harness on saved figures, with no reader.

Every complaint so far - the box in the wrong place, the reading stopping a third
of the way across, the finders returning three times as many bodies as there are
marks - is measurable on the page itself. This runs the model-free stages over a
folder of figures and writes what it measured, so a change can be judged against
the last report instead of against a fresh upload.

Where a figure has a hand-written expectation beside it (``page.expected.json``
holding the marks a person counted, or the plot box they drew), the report says
how far off we are; where it has none, the numbers still stand as a baseline that
the next run is compared to.
"""
import argparse
import json
from pathlib import Path

from . import axis_detect
from . import box_check
from . import coverage
from . import detectors
from . import plot_frame


def expectation(image):
    beside = Path(image).with_suffix('.expected.json')
    return json.loads(beside.read_text()) if beside.exists() else {}


def look(image, methods=None):
    """What python alone can say about one figure."""
    said = {'image': str(image)}
    ticks = axis_detect.detect_ticks(image)
    # The rules the figure prints are the plot's own edges; the tick-built box is
    # only reached for when nothing long enough to be an axis was drawn.
    measured = plot_frame.frame(image)
    box = measured['box'] if measured else axis_detect.plot_bbox_from_ticks(ticks)
    said['box_measured_from'] = (measured['measured_from'] if measured
                                 else 'the outermost ticks')
    said['ticks'] = {'across': len(ticks.get('x_tick_pixels') or []),
                     'up': len(ticks.get('y_tick_pixels') or [])}
    said['plot_bbox'] = box
    if box is None:
        said['note'] = 'no plot box could be measured from the printed rules and ticks'
        return said
    # The rules carry tick strokes that cross the box by construction, so ink is
    # allowed past an edge as far as the ticks this figure actually printed.
    ticks_reach = max(int(ticks.get('x_tick_band_px') or 0),
                      int(ticks.get('y_tick_band_px') or 0))
    said['box'] = box_check.score(image, box, beyond=ticks_reach)
    bank = detectors.run_all(image, box, outdir=None, methods=methods)
    marks = bank['pooled']
    said['marks'] = {'found': len(marks), 'corroborated': bank['corroborated'],
                     'by_method': bank['counts']}
    said['box_holds_the_marks'] = box_check.holds_marks(box, marks)
    said['reach_px'] = coverage.reach(marks)
    said['columns'] = len(coverage.columns([m['x'] for m in marks], said['reach_px'] or 0))
    want = expectation(image)
    if want.get('marks') is not None:
        said['against_the_count_a_person_made'] = {
            'expected': want['marks'], 'found': len(marks),
            'corroborated': bank['corroborated'],
            'off_by': len(marks) - want['marks'],
            'corroborated_off_by': bank['corroborated'] - want['marks']}
    if want.get('plot_bbox'):
        said['against_the_box_a_person_drew'] = {
            'expected': want['plot_bbox'],
            'moved': [round(float(a) - float(b), 1)
                      for a, b in zip(box, want['plot_bbox'])]}
    return said


def run(images, out=None, methods=None):
    report = {'figures': [look(image, methods) for image in images]}
    counted = [f['against_the_count_a_person_made'] for f in report['figures']
               if f.get('against_the_count_a_person_made')]
    report['summary'] = {
        'figures': len(report['figures']),
        'boxes_measured': sum(1 for f in report['figures'] if f.get('plot_bbox')),
        'boxes_standing_in_blank_paper': sum(
            1 for f in report['figures'] if (f.get('box') or {}).get('holds')),
        'counted_against_a_person': len(counted),
        'worst_count_error': max((abs(c['corroborated_off_by']) for c in counted),
                                 default=None)}
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(report, indent=2))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('images', nargs='+', help='figure images, or folders of them')
    ap.add_argument('--out', help='where to write the report')
    args = ap.parse_args(argv)
    found = []
    for given in args.images:
        path = Path(given)
        found += sorted(p for p in path.rglob('*.png')) if path.is_dir() else [path]
    print(json.dumps(run(found, args.out)['summary'], indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
