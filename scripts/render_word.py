"""Standalone DOCX renderer with an isolated LibreOffice profile per invocation."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def render(document, output):
    document = Path(document).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Render output must be empty; stale pages cannot be reused')
    output.mkdir(parents=True, exist_ok=True)
    office = os.environ.get('CASEFLOW_SOFFICE') or shutil.which('soffice.com') or shutil.which('soffice')
    poppler = os.environ.get('CASEFLOW_PDFTOPPM') or shutil.which('pdftoppm')
    if not office or not poppler:
        raise ValueError('LibreOffice and pdftoppm are required')
    with tempfile.TemporaryDirectory(prefix='caseflow-office-') as temp:
        profile = (Path(temp) / 'profile').as_uri()
        subprocess.run([office, '-env:UserInstallation=' + profile, '--headless', '--convert-to', 'pdf',
                        '--outdir', str(output), str(document)], check=True, capture_output=True, timeout=480)
    pdf = output / (document.stem + '.pdf')
    if not pdf.is_file() or not pdf.stat().st_size:
        raise ValueError('LibreOffice returned without a PDF')
    subprocess.run([poppler, '-png', '-r', '144', str(pdf), str(output / 'page')],
                   check=True, capture_output=True, timeout=300)
    pages = list(output.glob('page-*.png'))
    if not pages:
        raise ValueError('PDF rasterizer returned no pages')
    print('Rendered PDF and ' + str(len(pages)) + ' page images')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document', type=Path)
    parser.add_argument('--output_dir', type=Path, required=True)
    parser.add_argument('--emit_pdf', action='store_true')
    args = parser.parse_args()
    render(args.document, args.output_dir)
