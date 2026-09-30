"""Parent-run evidence generation; workers cannot certify their own renders/frames."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from caseflow import artifact, atomic_json, sha256, case_workspace, config_at
from verify_docx import verify
from video_evidence import generate


def registered_pipeline_profile(case, manifest, config):
    """Read this case's frozen registration; a worker label cannot switch protocol."""
    workspace = config.get('runner', {}).get('workspace_root')
    if not workspace or not manifest.get('source_sha256'):
        return None
    registry = Path(workspace) / '.batches'
    profiles = set()
    for path in registry.glob('*/manifest.json'):
        if path.is_symlink() or path.parent.is_symlink():
            continue
        batch = json.loads(path.read_text(encoding='utf-8-sig'))
        for entry in batch.get('cases', []):
            if ((not manifest.get('case_id') or entry.get('case_id') == manifest['case_id']) and
                    entry.get('source_sha256') == manifest['source_sha256'] and
                    case_workspace(path.parent, entry).resolve() == case.resolve()):
                profiles.add(batch.get('pipeline_profile') or 'legacy')
    if len(profiles) > 1 or profiles - {'legacy', 'efficient-v1', 'deliverable-first-v1'}:
        raise ValueError('Ambiguous or invalid frozen case pipeline profile')
    return next(iter(profiles), None)


def sync_trusted_capture_metadata(case, manifest, *, pipeline_profile=None):
    """Bind factual completion to the actual current trusted capture, never acceptance."""
    if pipeline_profile == 'legacy':
        # Legacy videos keep their original decode/render/review contract. Their
        # historical capture references do not claim a current trusted recording.
        return
    if not manifest.get('capture_report'):
        return
    pending = case / 'evidence/repair-status.json'
    if pending.is_file():
        note = json.loads(artifact(case, 'evidence/repair-status.json').read_text(encoding='utf-8-sig'))
        if note.get('status') == 'pending_owner_repair':
            raise ValueError('Pending owner repair before video binding: ' + str(note.get('required_action') or note.get('reason') or 'Read evidence/repair-status.json'))
    from capture_runner import validate_plan, service_ready, mark_recording_completed
    report = json.loads(artifact(case, manifest['capture_report']).read_text(encoding='utf-8-sig'))
    if report.get('mode') != 'record' or report.get('video') != manifest['video'] or report.get('video_sha256') != sha256(artifact(case, manifest['video'])):
        raise ValueError('Trusted capture does not bind current video')
    health = report.get('health', {})
    plan = json.loads(artifact(case, manifest['capture_plan']).read_text(encoding='utf-8-sig'))
    from urllib.parse import urlsplit
    validate_plan(case, health.get('case_id'), [urlsplit(plan['base_url']).port])
    current = service_ready(case, health.get('case_id'), plan)
    if any(current.get(k) != health.get(k) for k in ('case_id','workspace','version')):
        raise ValueError('Current service differs from trusted recording')
    mark_recording_completed(manifest, report)
    if 'ui_text_audit_sha256' in manifest:
        manifest['ui_text_audit_sha256'] = sha256(artifact(case, manifest['ui_text_audit']))


def produce(case, original, mode, config):
    case = Path(case).resolve(strict=True)
    cfg = config_at(Path(config))
    manifest = case / 'evidence/artifact-manifest.json'
    a = json.loads(manifest.read_text(encoding='utf-8'))
    if mode == 'word':
        document = artifact(case, a['revised_docx'])
        before = sha256(document)
        proof = verify(original, document, [artifact(case, c['png']) for c in a['charts']])
        if not proof['structural_preservation_ok'] or not proof['all_requested_figures_embedded']:
            raise ValueError('Original text/formula/media changed or final figure not embedded: ' + json.dumps(proof, ensure_ascii=False))
        if not proof['all_requested_figures_at_document_end']:
            raise ValueError('New Word figures/captions must be at document end; explanations stay in body: ' + json.dumps(proof['figure_placement'], ensure_ascii=False))
        if not proof['all_requested_figures_referenced_in_body']:
            raise ValueError('Each new Word figure needs its own reference in the body explanation: ' + json.dumps(proof['figure_placement'], ensure_ascii=False))
        if proof['original_sha256'] != a['source_sha256']:
            raise ValueError('Original hash does not match manifest')
        output = case / 'evidence/controlled-word' / f'{before[:12]}-{time.time_ns()}'
        output.mkdir(parents=True)
        env = dict(os.environ)
        runtime = cfg['runtime']
        env['CASEFLOW_SOFFICE'] = runtime['soffice']
        env['CASEFLOW_PDFTOPPM'] = runtime['pdftoppm']
        env['PATH'] = os.pathsep.join([str(Path(runtime['soffice']).parent), str(Path(runtime['pdftoppm']).parent), env.get('PATH', '')])
        command = [runtime['python'], '-X', 'utf8', runtime['docx_renderer'], str(document), '--output_dir', str(output), '--emit_pdf']
        run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=600)
        (output / 'render.log').write_text(run.stdout + '\n' + run.stderr, encoding='utf-8')
        if run.returncode:
            raise ValueError(f'Controlled Word render failed: {output / "render.log"}')
        pages = sorted(output.glob('page-*.png'), key=lambda p: int(re.search(r'page-(\d+)', p.name)[1]))
        from pypdf import PdfReader
        pdf = output / (document.stem + '.pdf')
        count = len(PdfReader(pdf).pages)
        if not pages or [int(re.search(r'page-(\d+)', p.name)[1]) for p in pages] != list(range(1, count + 1)):
            raise ValueError('Controlled render pages are missing or out of order')
        if sha256(document) != before or sha256(Path(original)) != a['source_sha256']:
            raise ValueError('Word or source changed during controlled rendering')
        preservation = output / 'preservation.json'
        atomic_json(preservation, proof)
        report = output / 'render.json'
        page_hashes = {p.relative_to(case).as_posix(): sha256(p) for p in pages}
        atomic_json(report, {'docx_sha256': before, 'pdf': pdf.relative_to(case).as_posix(), 'pdf_sha256': sha256(pdf),
                             'page_count': count, 'page_hashes': page_hashes, 'command': command, 'exit_code': run.returncode})
        a.update(rendered_pages=list(page_hashes), preservation_report=preservation.relative_to(case).as_posix(),
                 render_report=report.relative_to(case).as_posix())
        verification_path = artifact(case, a['test_report'])
        verification = json.loads(verification_path.read_text(encoding='utf-8'))
        verification.update(rendered_docx_sha256=before, rendered_page_count=count)
        atomic_json(verification_path, verification)
        generated = [preservation, report, pdf, *pages]
    else:
        video = artifact(case, a['video'])
        output = case / 'recording/controlled-evidence' / f'{sha256(video)[:12]}-{time.time_ns()}'
        settings = cfg['video']
        result = generate(video, output, settings['sample_fps'], settings['min_seconds'], settings['max_seconds'],tool_paths=cfg['runtime'])
        sync_trusted_capture_metadata(case, a, pipeline_profile=registered_pipeline_profile(case, a, cfg))
        a.update(video_timeline=(output / 'timeline.json').relative_to(case).as_posix(),
                 video_contact_sheets=[Path(p['file']).relative_to(case).as_posix() for p in result['contact_sheets']])
        generated = [output / 'timeline.json', *[Path(p['file']) for p in result['frames'] + result['contact_sheets']]]
    atomic_json(manifest, a)
    return {'mode': mode, 'files': {p.relative_to(case).as_posix(): sha256(p) for p in generated},
            'manifest_fields': {k: a[k] for k in (('rendered_pages', 'preservation_report', 'render_report') if mode == 'word' else ('video_timeline', 'video_contact_sheets'))}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['word', 'video'])
    p.add_argument('case', type=Path)
    p.add_argument('original', type=Path)
    p.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'config.json')
    a = p.parse_args()
    print(json.dumps(produce(a.case, a.original, a.mode, a.config), ensure_ascii=False))


if __name__ == '__main__':
    main()
