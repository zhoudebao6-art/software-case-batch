"""One invocation's file hashes, never a persisted validation/approval cache."""
import os
from pathlib import Path


class CheckedHashes:
    def __init__(self, digest):
        self.digest = digest
        self.values = {}

    @staticmethod
    def signature(path):
        s = path.stat()
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    def __call__(self, path):
        path = Path(path)
        key = os.path.normcase(str(path.absolute()))
        before = self.signature(path)
        if key in self.values:
            _, original, value = self.values[key]
            if before != original:
                raise ValueError('Construction file changed during this check: ' + str(path))
            return value
        value = self.digest(path)
        if self.signature(path) != before:
            raise ValueError('Construction file changed while being hashed: ' + str(path))
        self.values[key] = (path, before, value)
        return value

    def finish(self):
        for path, before, _ in self.values.values():
            if self.signature(path) != before:
                raise ValueError('Construction file changed before check completed: ' + str(path))


def compact_result(result, command, workspace, plan=None, evidence=None):
    """Only reduce stdout detail; retain states, failures and next actions verbatim."""
    heavy = {'implementation_hashes', 'input_files', 'test_files',
             'reviewed_evidence', 'evidence_hashes'}
    def walk(value):
        if isinstance(value, dict):
            return {k: (v if k in {'errors','warnings','reason','changed_dependencies'} else
                        {'omitted_items': len(v)} if k in heavy and isinstance(v, (dict, list))
                        else walk(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value
    value = walk(result)
    argv = ['proflow.py', command, '--workspace', str(workspace)]
    if plan: argv += ['--plan', str(plan)]
    if evidence: argv += ['--evidence', str(evidence)]
    return {'output_mode': 'compact-not-proof', 'result': value,
            'detail_argv': argv,
            'existing_records': [str(Path(workspace)/'.product-v2'/name)
                                 for name in ('run.json', 'build-checks.json', 'source-manifest.json')],
            'limitation': 'Full checks ran normally. Only repeated dependency lists are omitted from stdout; this summary is not review evidence. Read existing files only when needed.'}
