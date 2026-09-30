"""Detect real links without mistaking Windows short-name aliases for links."""
import stat
from pathlib import Path


def has_path_link(path: Path) -> bool:
    """Check the path and its ancestors without following filesystem links.

    Comparing resolve() to absolute() rejects valid Windows 8.3 aliases. Use
    filesystem metadata instead; junctions and other reparse points still fail
    closed, including ancestors of a destination that does not exist yet.
    """
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & 0x400):
            return True
    return False
