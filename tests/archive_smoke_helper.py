"""Explicit cross-volume fixture smoke; never discovered or run automatically.

The caller must opt in with a fresh UUID hex. F business products are not read,
scanned or adopted. The tiny dedicated fixture and report remain for review.
"""
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import archive_products as archive
from common import digest, file_map, no_links, state, write_json
from proflow import revision_chain


def run_cross_volume_smoke(run_id):
    if os.name != 'nt' or not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
        raise ValueError('Windows and an explicit fresh lowercase UUID hex are required')
    temp_root = no_links(r'D:\codex+\temp')
    f_parent = no_links(r'F:\研发图表')
    destination_root = no_links(f_parent / ('.archive-smoke-' + run_id))
    if not temp_root.is_dir() or not f_parent.is_dir():
        raise ValueError('Explicit D temp and F parent must already exist; no fallback')
    if destination_root.exists():
        raise ValueError('A fresh dedicated smoke root is required; no adoption or overwrite')
    if temp_root.stat().st_dev == f_parent.stat().st_dev:
        raise ValueError('The fixture must exercise two distinct actual volumes')
    # Reuse only the isolated test constructor; it creates no real case records.
    import test_archive_products as fixtures
    with patch.dict(os.environ, {'TEMP': str(temp_root), 'TMP': str(temp_root), 'TMPDIR': str(temp_root)}):
        import tempfile
        old_tempdir = tempfile.tempdir
        tempfile.tempdir = str(temp_root)
        fixture = fixtures.ArchiveTests(methodName='runTest')
        try:
            fixture.setUp()
        finally:
            tempfile.tempdir = old_tempdir
    root = no_links(fixture.root)
    if root.parent != temp_root:
        raise ValueError('Unexpected fixture root; retain it for inspection')
    destination_root.mkdir()  # Exclusive new directory; never creates the F parent.
    frozen = {str(path): digest(path) for path in
              (fixture.final, fixture.publish, fixture.work / '.product-v2/run.json', fixture.proof)}
    link = {'workspace': str(fixture.work), 'output': str(fixture.source),
            'receipt_sha256': digest(fixture.final),
            'system_files': {key[len('模拟系统/'):]: value for key, value in fixture.files.items()
                             if key.startswith('模拟系统/')}}
    args = (fixture.source_root, destination_root, fixture.batch_root, fixture.state_root)
    setup = {'fixture_only': True, 'run_id': run_id, 'source_root': str(args[0]),
             'destination_root': str(args[1]), 'batch_root': str(args[2]),
             'state_root': str(args[3]), 'files': fixture.files, 'frozen_sha256': frozen}
    write_json(root / 'cross-volume-fixture.json', setup)
    plan = archive.plan(*args)
    write_json(root / 'cross-volume-plan.json', plan)
    if plan['retained'] or len(plan['eligible']) != 1:
        raise ValueError('Fixture plan failed; retain all fixtures and evidence')
    result = archive.apply(*args)
    write_json(root / 'cross-volume-apply.json', result)
    destination = destination_root / '批次/batch-a/case-a'
    if result['retained'] or len(result['archived']) != 1 or fixture.source.exists():
        raise ValueError('Cross-volume fixture archive incomplete; retain all evidence')
    if file_map(destination) != fixture.files or frozen != {path: digest(path) for path in frozen}:
        raise ValueError('Cross-volume fixture bytes or frozen records differ')
    following = root / 'following-revision'
    following.mkdir()
    with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(fixture.state_root)}):
        if state(fixture.work)[1] != destination or revision_chain(following, link)[0]['output'] != destination:
            raise ValueError('Cross-volume locator or inherited revision failed')
    report = dict(setup, status='verified-fixture', product=str(destination),
                  source_removed=True, frozen_receipts_unchanged=True,
                  locator_verified=True, inherited_revision_verified=True,
                  source_device=temp_root.stat().st_dev, destination_device=f_parent.stat().st_dev,
                  report=str(root / 'cross-volume-report.json'), business_materials_used=False,
                  cleanup='Dedicated D and F fixtures retained for review; no automatic recursive cleanup')
    write_json(root / 'cross-volume-report.json', report)
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(run_cross_volume_smoke(args.run_id), ensure_ascii=False, indent=2))
