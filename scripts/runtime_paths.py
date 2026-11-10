"""Use the environment entry's configured cache root, never a fixed drive."""
import os
from pathlib import Path
from common import no_links, read_json


def cache_root():
    value = os.environ.get('SCB_PRO_CACHE_ROOT')
    if not value:
        config = Path(__file__).resolve().parents[1] / 'local.config.json'
        value = read_json(config).get('cache_root') if config.is_file() else None
    value = value or r'E:\codex+'
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError('cache_root must be an explicit absolute directory')
    return no_links(value)


def checked_temp_root():
    expected = cache_root() / 'temp'
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        value = os.environ.get(name, '')
        if not value or not Path(value).is_absolute() or no_links(value) != expected:
            raise ValueError(f'Load installed Enter-Environment.ps1; {name} must be {expected}')
    if not expected.is_dir():
        raise ValueError('Configured private temp root must already exist')
    return expected
