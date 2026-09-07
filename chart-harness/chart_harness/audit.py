"""Portable exports and cumulative accounting from append-only request journals."""
import csv
import json
from collections import Counter
from pathlib import Path

from .provider import normalize_usage


def usage_report(directory):
    records = []
    for path in sorted(Path(directory).rglob('usage.jsonl')):
        for line in path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    events = Counter(r['event'] for r in records)
    finished = [r for r in records if r['event'] == 'attempt_finished']
    incomplete = max(0, events['attempt_started'] - len(finished))
    exchange_events = [r for r in records if r['event'] == 'external_exchange']
    external = len({r.get('raw_artifact',r.get('cache_key')) for r in exchange_events})
    keys = normalize_usage(None)
    totals, unknown = {}, {}
    for key in keys:
        values = [normalize_usage(r.get('reported_usage'))[key] for r in finished]
        totals[key] = sum(v for v in values if v is not None)
        unknown[key] = sum(v is None for v in values) + incomplete + external
    costs = [r.get('estimated_cost_usd') for r in finished]
    unknown_cost = sum(c is None for c in costs) + incomplete + external
    return {
        'events': dict(events), 'api_attempts': events['attempt_started'],
        'external_exchange_packets_consumed': external,
        'duplicate_exchange_consumption_events': len(exchange_events)-external,
        'known_token_subtotals': totals, 'unknown_usage_counts': unknown,
        'known_cost_subtotal_usd': sum(c for c in costs if c is not None),
        'total_cost_usd': None if unknown_cost else sum(costs),
        'unknown_cost_count': unknown_cost,
        'notes': [
            'Cached input and reasoning are subsets; do not add them to input/output totals.',
            'An exchange packet can involve an unmetered external tool loop; packets are not inference counts.',
            'Costs use user-supplied prices and reported API counters, excluding local compute and human review.',
            'Unknown means unmeasured, not free. Pending external packets are not counted as consumed.'
        ]
    }


def export_batch(result, outdir):
    """Export partial observations with explicit chart status and source pixels."""
    outdir = Path(outdir)
    rows = []
    for panel in result['panels']:
        for row in panel.get('rows', []):
            rows.append({
                'source_sha256': result['source_sha256'], 'pdf_page': result['page'],
                'panel': panel['panel'], 'chart_status': result['status'], **row
            })
    fields = ['source_sha256', 'pdf_page', 'panel', 'chart_status', 'candidate_id',
              'series_id', 'series_label', 'pixel_x', 'pixel_y', 'page_pixel_x', 'page_pixel_y',
              'x', 'y', 'x_unit', 'y_unit', 'x_low', 'x_high', 'y_low', 'y_high',
              'status', 'raw_image_support', 'reason', 'flags']
    paths = {}
    for name, selected in [('observed', [r for r in rows if r['status'] == 'observed']),
                           ('all_candidates', rows)]:
        path = outdir / (name + '.csv')
        with path.open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in selected:
                writer.writerow({**row, 'flags': ';'.join(row.get('flags', []))})
        paths[name + '_csv'] = str(path)
    return paths
