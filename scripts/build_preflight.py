"""Read-only construction checks. No rendering, recording, service or model calls."""
import argparse
import json
from pathlib import Path
import zipfile

from caseflow import Blocked, artifact, read_json, sha256, validate_build_contract
from verify_docx import verify


def check(case, original, *, source_hash=None):
    case, original = Path(case).resolve(), Path(original).resolve()
    errors = []
    expected = source_hash or sha256(original)
    if sha256(original) != expected:
        errors.append('Source file no longer matches frozen source_sha256')
    try:
        validate_build_contract(case, expected)
    except (Blocked, OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    word = None
    try:
        manifest = read_json(artifact(case, 'evidence/artifact-manifest.json'))
        word = verify(original, artifact(case, manifest['revised_docx']),
                      [artifact(case, c['png']) for c in manifest['charts']])
        for key in ('structural_preservation_ok', 'all_requested_figures_embedded',
                    'all_requested_figures_at_document_end', 'all_requested_figures_referenced_in_body'):
            if not word.get(key):
                errors.append('Word: ' + key + ' failed')
    except (Blocked, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        errors.append('Word: ' + str(exc))
    return {'ok': not errors, 'errors': errors, 'word': word,
            'independent_review': 'not_performed',
            'note': 'Mechanical preflight only. Still inspect final rendered pages, actual browser transitions and video.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('original', type=Path)
    parser.add_argument('--source-sha256')
    args = parser.parse_args()
    result = check(args.case, args.original, source_hash=args.source_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['ok'] else 2)
