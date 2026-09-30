"""Local-only Windows setup. Never copy credentials or overwrite local config."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time


def first_file(candidates):
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


def discover(root):
    root = Path(root).resolve()
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
    node_modules = next((p for p in [root / 'node_modules', bundled / 'node/node_modules']
                         if (p / 'playwright/package.json').is_file()), root / 'node_modules')
    program_files = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
    runtime = {
        'python': first_file([root / '.venv/Scripts/python.exe', bundled / 'python/python.exe', sys.executable]),
        'node': first_file([shutil.which('node'), bundled / 'node/node.exe', program_files / 'nodejs/node.exe']),
        'node_modules': str(node_modules),
        'docx_renderer': str(root / 'scripts/render_word.py'),
        'soffice': first_file([shutil.which('soffice.com'), shutil.which('soffice'), program_files / 'LibreOffice/program/soffice.com']),
        'pdftoppm': first_file([shutil.which('pdftoppm'), bundled / 'native/poppler/Library/bin/pdftoppm.exe']),
    }
    for key in ('ffmpeg', 'ffprobe'):
        runtime[key] = first_file([shutil.which(key), bundled / f'native/ffmpeg/bin/{key}.exe'])
    return runtime


def write_config(path, data):
    # Exclusive creation prevents an installation rerun from resetting live settings.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def install_skill(root, codex_home):
    root = Path(root).resolve()
    source = root / 'skill/SKILL.md'
    body = source.read_text(encoding='utf-8')
    body = re.sub(r'\]\(\.\./([^\)]+)\)', lambda m: '](<' + root.as_posix() + '/' + m[1] + '>)', body)
    body += '\n\n本机安装位置：`' + str(root) + '`。先读取此目录的 config.json，所有项目路径以该目录为基准。\n'
    target = Path(codex_home) / 'skills/software-case-batch/SKILL.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding='utf-8') != body:
        shutil.copy2(target, target.with_name('SKILL.md.backup-' + str(time.time_ns())))
    target.write_text(body, encoding='utf-8')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--install-skill', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    config = root / 'config.json'
    if config.exists():
        print('Existing config.json preserved. Edit runtime paths there if necessary.')
    else:
        cfg = json.loads((root / 'config.example.json').read_text(encoding='utf-8'))
        cfg['runtime'] = discover(root)
        from caseflow import native_codex, Blocked
        try:
            cfg['runner']['codex_executable'] = str(native_codex(cfg))
        except Blocked:
            pass
        write_config(config, cfg)
        print('Created local config.json; no batch or model call started.')
    if args.install_skill:
        print('Installed skill: ' + str(install_skill(root, Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))))
    print('Next: .\\scripts\\caseflow.ps1 doctor --smoke')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
