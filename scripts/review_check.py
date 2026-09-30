"""Read-only evidence checklist, never infers which evidence was inspected."""
import argparse
import json
from collections import Counter
from pathlib import Path


def check_ids(request, ids):
    index = request['evidence']
    counts = Counter(ids)
    missing = {key: path for key, path in index.items() if key not in counts}
    unknown = sorted(set(ids) - set(index))
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    return {'complete': not (missing or unknown or duplicates), 'missing': missing,
            'unknown': unknown, 'duplicates': duplicates,
            'note': 'List completeness only; no content review, verdict, hash binding or inferred read coverage.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('--ids', nargs='*', required=True)
    args = parser.parse_args()
    result = check_ids(json.loads(args.request.read_text(encoding='utf-8')), args.ids)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['complete'] else 2)
