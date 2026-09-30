"""Summarize recorded stage costs without asking another model or scanning cases."""
import argparse
import json
from pathlib import Path
from statistics import median

def collect(root):
    stages, batches = {}, []
    for folder in sorted((Path(root) / '.batches').iterdir()):
        if not folder.is_dir() or not (folder / 'state').is_dir():
            continue
        summary = {'batch_id': folder.name, 'cases': 0, 'delivered': 0, 'blocked': 0}
        for path in (folder / 'state').glob('*.json'):
            if path.name.startswith('.'):
                continue
            state = json.loads(path.read_text(encoding='utf-8'))
            summary['cases'] += 1
            if state.get('stage') in ('delivered', 'blocked'):
                summary[state['stage']] += 1
            for call in state.get('calls', []):
                row = stages.setdefault(call['stage'], {'durations': [], 'failed': 0, 'input_tokens': 0, 'output_tokens': 0})
                row['durations'].append(call.get('duration_seconds', 0))
                row['failed'] += int(call.get('exit_code') != 0 or bool(call.get('timed_out')))
                usage = call.get('token_usage') or {}
                for key in ('input_tokens', 'output_tokens'):
                    row[key] += usage.get(key, 0)
        batches.append(summary)
    result = {}
    for stage, row in stages.items():
        durations = row.pop('durations')
        result[stage] = {**row, 'calls': len(durations), 'total_minutes': round(sum(durations)/60, 1),
                         'median_minutes': round(median(durations)/60, 1), 'max_minutes': round(max(durations)/60, 1)}
    return {'batches': batches, 'stages': result, 'note': 'Historical recorded calls only; concurrent durations are not elapsed batch time. Missing token usage is not estimated.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = collect(args.root)
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
