"""Check the exact Git index before committing/publishing; never prints secrets."""
import json
from pathlib import Path
import re
import subprocess


def audit(root):
    root = Path(root)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    violations = []
    files = []
    forbidden_parts = {'cases', 'evidence', '.runtime', '.venv', 'node_modules', '.codex'}
    extensions = {'.py', '.ps1', '.cjs', '.md', '.json', '.txt', '.yml', '.yaml'}
    secret_patterns = [r'gh[pousr]_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{30,}',
                       r'sk-[A-Za-z0-9_-]{30,}', r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    for name in filter(None, names):
        path = Path(name)
        # Read staged bytes, not a later unstaged edit.
        blob = subprocess.check_output(['git', 'show', ':' + name], cwd=root)
        bad = (set(path.parts) & forbidden_parts or path.name in {'config.json', 'auth.json'} or
               (path.suffix not in extensions and name not in {'.gitignore', '.gitattributes'}) or
               len(blob) > 2_000_000)
        if bad:
            violations.append({'path': name, 'reason': 'not source-only allowlist'})
        try:
            text = blob.decode('utf-8-sig')
            if any(re.search(p, text) for p in secret_patterns):
                violations.append({'path': name, 'reason': 'possible credential; inspect locally'})
        except UnicodeDecodeError:
            violations.append({'path': name, 'reason': 'unexpected binary'})
        files.append(name)
    return {'ok': bool(files) and not violations, 'file_count': len(files), 'violations': violations}


if __name__ == '__main__':
    result = audit(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
