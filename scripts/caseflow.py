"""Conservative, resumable batch orchestration for one Word file per case.

The CLI never starts a case from ``plan``. ``run`` requires the exact planned
manifest and refuses to replace any existing delivery.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from path_safety import has_path_link


class Blocked(RuntimeError):
    pass


class Busy(Blocked):
    pass


class WorkerBlocked(Blocked):
    """A worker's explicit blocker, retained before generic artifact errors."""
    def __init__(self, blocker):
        self.blocker = blocker
        super().__init__(blocker['message'])


class Drained(RuntimeError):
    """A requested checkpoint stop; not an environment or quality failure."""
    pass


class ReviewRerouted(RuntimeError):
    """Withdraw a waiting ticket after an explicitly requested route change."""
    pass


REVIEW_PROFILES = {
    'standard': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra', 'slot': 'review'},
    'expedited': {'model': 'gpt-6-astra', 'reasoning_effort': 'low', 'slot': 'review_expedited'},
}


def selected_review_route(folder, case_id, cfg=None):
    standard = dict(REVIEW_PROFILES['standard'])
    if cfg is not None:
        # Honor an explicitly loaded configuration; do not silently replace a
        # legacy caller's model with the current default.
        standard.update(cfg['models']['reviewer'])
    path = folder / 'control.json'
    control = read_json(path) if path.is_file() else {}
    selection = control.get('review_routes', {}).get(case_id, control.get('review_route'))
    if selection is None:
        return {'profile': 'standard', **standard, 'authorization_id': None}
    if (not isinstance(selection, dict) or selection.get('profile') not in REVIEW_PROFILES or
            not isinstance(selection.get('authorization_id'), str) or not selection['authorization_id']):
        raise Blocked('Invalid explicit review route authorization')
    route = standard if selection['profile'] == 'standard' else REVIEW_PROFILES[selection['profile']]
    return {**selection, **route}


def review_call_config(cfg, route):
    reviewer = {key: route[key] for key in ('model', 'reasoning_effort')}
    return {**cfg, 'models': {**cfg['models'], 'reviewer': reviewer}}


def review_record_allowed(record, state):
    if record.get('sandbox') != 'read-only':
        return False
    profile = record.get('review_profile', 'standard')
    expected = REVIEW_PROFILES.get(profile)
    if profile == 'standard' and record.get('model') == 'gpt-6-sol':
        # Historical passes retain their actual model identity. Current calls
        # are additionally checked against the selected route before saving.
        expected = {**expected, 'model': 'gpt-6-sol'}
    if not expected or any(record.get(key) != expected[key] for key in ('model', 'reasoning_effort')):
        return False
    if profile == 'expedited':
        authorization = state.get('review_authorizations', {}).get(record.get('review_authorization_id'))
        return isinstance(authorization, dict) and authorization.get('profile') == profile
    return True


def check_control(folder):
    path=folder/'control.json'
    control=read_json(path) if path.is_file() else {}
    if control.get('drain'):
        raise Drained('Requested drain reached a safe stage boundary')
    return control


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(10):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 9:
                    raise
                time.sleep(.01 * (attempt + 1))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict:
    # Windows can briefly deny opening a file while atomic_json replaces it.
    # Match the bounded writer retry; never return an empty/default state or
    # alter ACLs. Persistent denial and invalid JSON still propagate unchanged.
    for attempt in range(10):
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except PermissionError:
            if os.name != 'nt' or attempt == 9:
                raise
            time.sleep(.01 * (attempt + 1))


def compact_case_state(state: dict, path: Path) -> dict:
    """Keep full calls/evidence in the case state, not every batch heartbeat."""
    fields = ('case_id', 'case_name', 'workspace', 'stage', 'previous_stage',
              'active_stage', 'active_started_at', 'active_review_profile', 'waiting_stage',
              'failed_stage', 'reason', 'checkpoint_waiting', 'delivery', 'review_mode',
              'recording_pending', 'repairs_visual', 'repairs_video', 'repairs_final',
              'review_calls_started')
    result = {key: state[key] for key in fields if key in state}
    result.update(state_file=str(path), call_count=len(state.get('calls', [])),
                  script_call_count=len(state.get('script_calls', [])))
    for kind in ('visual', 'video', 'final'):
        review = state.get(kind + '_review')
        if review:
            result[kind + '_review'] = {k: review[k] for k in
                ('verdict', 'path', 'model', 'reasoning_effort', 'report_sha256') if k in review}
    return result


def inside(path: Path, root: Path, *, must_exist: bool = False) -> Path:
    root = root.resolve(strict=True)
    resolved = path.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise Blocked(f"Path leaves allowed root: {path}")
    return resolved


def artifact(case: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise Blocked(f"Unsafe artifact path: {name!r}")
    p = inside(case / name, case, must_exist=True)
    if not p.is_file() or p.stat().st_size == 0:
        raise Blocked(f"Missing or empty artifact: {name}")
    return p


def good_image(path: Path) -> bool:
    try:
        from PIL import Image
    except ImportError as exc:
        raise Blocked("Use configured bundled Python; Pillow is required for image verification") from exc
    try:
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG"}:
                return False
            image.verify()
        with Image.open(path) as image:
            image.load()
        return True
    except (OSError, ValueError, SyntaxError):
        return False


def good_docx(path: Path) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as z:
        return z.testzip() is None and "word/document.xml" in z.namelist()


def good_csv(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = csv.reader(f)
            header = next(rows)
            if len(header) < 2 or not all(x.strip() for x in header):
                return False
            count = 0
            for row in rows:
                if not row:
                    continue
                if len(row) != len(header):
                    return False
                count += 1
        return count > 0
    except (OSError, UnicodeError, StopIteration, csv.Error):
        return False


def good_mp4(path: Path) -> bool:
    with path.open("rb") as f:
        h = f.read(12)
    return len(h) == 12 and h[4:8] == b"ftyp"


def config_at(path: Path) -> dict:
    cfg = read_json(path.resolve(strict=True))
    runner = cfg.get("runner", {})
    base = path.resolve().parent
    def local_path(value):
        item = Path(os.path.expandvars(str(value))).expanduser()
        return str((item if item.is_absolute() else base / item).resolve())
    runner['workspace_root'] = local_path(runner.get('workspace_root', 'cases'))
    runner['protected_source_roots'] = [local_path(p) for p in runner.get('protected_source_roots', [])]
    if runner.get('codex_executable'):
        runner['codex_executable'] = local_path(runner['codex_executable'])
    if cfg.get('standards'):
        cfg['standards'] = local_path(cfg['standards'])
    for key, value in cfg.get('runtime', {}).items():
        if value:
            cfg['runtime'][key] = local_path(value)
    root = Path(runner['workspace_root'])
    prompts = Path(runner.get("prompts_dir", "prompts"))
    if not prompts.is_absolute():
        prompts = base / prompts
    cfg["_root"] = root
    cfg["_prompts"] = prompts.resolve()
    cfg["_base"] = base
    cfg["_config_path"] = path.resolve()
    if cfg.get("models", {}).get("allow_fallback") is not False:
        raise Blocked("Model fallback must be disabled")
    if cfg.get("models", {}).get("builder") not in (
            {"model": "gpt-6-sol", "reasoning_effort": "high"},
            {"model": "gpt-6.1-sol", "reasoning_effort": "high"}):
        raise Blocked("Builder route must be an explicitly configured Sol model with high effort")
    if 'repairer' in cfg.get('models', {}) and cfg['models']['repairer'] != {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'}:
        raise Blocked('Explicit repair route must be gpt-6.1-sol with ultra effort')
    if cfg.get("models", {}).get("reviewer") not in (
            {"model": "gpt-6-sol", "reasoning_effort": "ultra"},
            {"model": "gpt-6.1-sol", "reasoning_effort": "ultra"}):
        raise Blocked("Reviewer route must be an explicitly configured Sol model with ultra effort")
    expedited = cfg.get('models', {}).get('expedited_reviewer', {'model': 'gpt-6-astra', 'reasoning_effort': 'low'})
    if expedited != {'model': 'gpt-6-astra', 'reasoning_effort': 'low'}:
        raise Blocked('Expedited reviewer route must be gpt-6-astra/low')
    if runner.get("review_mode", "split") not in {"split", "combined_final"}:
        raise Blocked("Unknown review mode")
    if runner.get('pipeline_profile', 'legacy') not in {'legacy', 'efficient-v1', 'deliverable-first-v1'}:
        raise Blocked('Unknown pipeline profile')
    if runner.get('delivery_profile', 'full') not in {'full', 'word-video'}:
        raise Blocked('Unknown delivery profile')
    if type(cfg.get('execution', {}).get('fair_queue', False)) is not bool:
        raise Blocked('fair_queue must be a boolean')
    for key in ("max_review_calls_per_case", "max_astra_calls_per_case", "max_final_review_repairs", "max_repairs_per_review"):
        if runner.get(key) is not None and (type(runner[key]) is not int or runner[key] < (1 if key in {"max_review_calls_per_case", "max_astra_calls_per_case"} else 0)):
            raise Blocked(f"Invalid {key}")
    for key, default in (("case_concurrency", 1), ("review_concurrency", 1), ("expedited_review_concurrency", 1), ("recording_concurrency", 1), ("evidence_concurrency", 1)):
        value = cfg.get("execution", {}).get(key, default)
        if type(value) is not int or not 1 <= value <= 8:
            raise Blocked(f"{key} must be an integer from 1 to 8")
    for key, default in (("recording_min_available_mb", 0), ("recording_reserve_mb", 0)):
        value = cfg.get("execution", {}).get(key, default)
        if type(value) is not int or value < 0:
            raise Blocked(f"{key} must be a non-negative integer")
    return cfg


def case_name(path: Path, source_root: Path) -> str:
    # The parent folder names a case only when it contains exactly one Word.
    siblings = [p for p in path.parent.iterdir() if p.is_file() and p.suffix.lower() in {".docx", ".doc"} and not p.name.startswith("~$")]
    name = path.parent.name if path.parent != source_root and len(siblings) == 1 else path.stem
    for prefix in ("技术项目优化说明书+", "技术项目优化说明书＋"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.strip() or path.stem


def safe_case_name(name: str) -> str:
    value = "".join(c if c not in '<>:"/\\|?*' and ord(c) >= 32 else "_" for c in name).strip(" .") or "未命名案件"
    if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", value, re.I):
        value = "案件_" + value
    return value[:80].rstrip(" .")


def workspace_title(name: str) -> str:
    return safe_case_name(re.sub(r"^技术项目优化说明书[+＋]?", "", name).strip())


def prepare_control_directories(root: Path) -> None:
    for name in (".batches", ".runtime"):
        path = root / name
        if has_path_link(path):
            raise Blocked("Control directory link refused")
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            import ctypes
            target = ctypes.c_wchar_p(str(path))
            attributes = ctypes.windll.kernel32.GetFileAttributesW(target)
            if attributes != -1:
                ctypes.windll.kernel32.SetFileAttributesW(target, attributes | 2)


def unique_name(base: str, used: set[str]) -> str:
    result, index = base, 2
    while result.casefold() in used:
        result = f"{base}（{index}）"
        index += 1
    used.add(result.casefold())
    return result


def case_workspace(folder: Path, entry: dict) -> Path:
    name = entry.get("workspace_name", entry["case_id"])
    if not isinstance(name, str) or not name or name.casefold() in {".", "..", ".runtime", "state", "reviews", "publish-intents", "logs"} or any(c in name for c in '/\\:<>"|?*') or name.rstrip(" .") != name:
        raise Blocked("Unsafe case workspace name")
    if "workspace_relative" in entry:
        relative = entry["workspace_relative"]
        parts = relative.split("/") if isinstance(relative, str) else []
        if len(parts) != 2 or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", parts[0]) or parts[1] != name:
            raise Blocked("Unsafe monthly workspace path")
        root = folder.parent.parent if folder.parent.name == ".batches" else folder.parent
        return root / parts[0] / name
    return folder / name


def batch_folder(cfg: dict, batch: dict | str) -> Path:
    bid = batch["batch_id"] if isinstance(batch, dict) else batch
    root = cfg["_root"]
    found = []
    if root.exists():
        for p in [*root.glob("*/manifest.json"), *root.glob(".batches/*/manifest.json")]:
            if p.is_symlink() or p.parent.is_symlink():
                continue
            try:
                if read_json(p).get("batch_id") == bid:
                    found.append(p.parent)
            except FileNotFoundError:
                # A manifest can disappear after the glob snapshot while a
                # concurrent atomic publish completes; re-scan on the next
                # command instead of treating it as an existing batch.
                continue
            except (PermissionError, OSError, ValueError) as exc:
                # Never hide an unreadable/corrupt manifest and accidentally
                # create a second batch folder with the same identity.
                raise Blocked(f"Cannot safely read registered batch manifest: {p}") from exc
    if len(found) > 1:
        raise Blocked("Duplicate batch identity on disk")
    return found[0] if found else root / ".batches" / bid


def assign_workspaces(m: dict, folder: Path, root: Path, *, include_started: bool = False) -> bool:
    # Old started workspaces keep their paths, hashes and resumable evidence.
    month = m.get("workspace_month", time.strftime("%Y-%m"))
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month):
        raise Blocked("Invalid workspace month")
    used = {"state", "reviews", "publish-intents", "logs"}
    month_dir = root / month
    if month_dir.exists():
        used.update(p.name.casefold() for p in month_dir.iterdir())
    for manifest in [*root.glob("*/manifest.json"), *root.glob(".batches/*/manifest.json")]:
        if manifest.is_symlink() or manifest.parent.is_symlink():
            continue
        for other in read_json(manifest).get("cases", []):
            relative = other.get("workspace_relative", "")
            if relative.startswith(month + "/"):
                used.add(relative.split("/", 1)[1].casefold())
    used.update(e["workspace_name"].casefold() for e in m["cases"] if e.get("workspace_name"))
    changed = False
    for e in m["cases"]:
        if e.get("workspace_name"):
            case_workspace(folder, e)
            continue
        if not include_started and folder and ((folder / e["case_id"]).exists() or state_at(folder, e["case_id"]).exists()):
            continue
        e["workspace_name"] = unique_name(workspace_title(e["case_name"]), used)
        e["workspace_relative"] = month + "/" + e["workspace_name"]
        e["delivery_name"] = e["workspace_name"]
        changed = True
    if changed:
        m["workspace_month"] = month
    return changed


def migrate_batch(cfg: dict, ref: str) -> dict:
    # Import lazily so ordinary execution never runs migration/process inspection.
    import importlib.util
    spec = importlib.util.spec_from_file_location("caseflow_migration", Path(__file__).with_name("migrate_batch.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from types import SimpleNamespace
    return module.migrate(cfg, ref, SimpleNamespace(**globals()))


def manifest_for(source: Path) -> dict:
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise Blocked("Input must be a directory")
    entries = []
    for path in sorted(source.rglob("*"), key=lambda x: str(x).casefold()):
        # A batch may publish to the explicitly selected _成品 folder inside
        # its source directory. Published Word files are never new inputs.
        if "_成品" in path.relative_to(source).parts[:-1]:
            continue
        if not path.is_file() or path.name.startswith("~$") or path.suffix.lower() not in {".doc", ".docx"}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise Blocked(f"Source Word links outside input: {path}")
        rel = path.relative_to(source).as_posix()
        digest = sha256(path)
        reason = "legacy .doc unsupported" if path.suffix.lower() == ".doc" else None
        if not reason and not good_docx(path):
            reason = "invalid or encrypted .docx"
        cid = hashlib.sha256((rel.casefold() + "\0" + digest).encode("utf-8")).hexdigest()[:16]
        entries.append({"case_id": cid, "case_name": case_name(path, source), "relative_path": rel,
                        "source_path": str(path.resolve()), "source_sha256": digest, "source_size": path.stat().st_size,
                        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "blocked_reason": reason})
    if not entries:
        raise Blocked("No Word files found")
    key = json.dumps({"source": str(source).casefold(), "entries": [(e["relative_path"], e["source_sha256"]) for e in entries]}, ensure_ascii=False, sort_keys=True)
    bid = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return {"schema_version": 1, "batch_id": bid, "source_root": str(source),
            "output_root": str(source.parent / (source.name + "1")), "cases": entries}


def plan(cfg: dict, source: Path) -> dict:
    source = source.resolve(strict=True)
    root = cfg["_root"]
    if source == root or root.is_relative_to(source) or source.is_relative_to(root):
        raise Blocked("Source overlaps internal workspace")
    protected = [cfg["_base"] / "evidence", cfg["_base"] / "examples"]
    protected += [Path(p) for p in cfg.get("runner", {}).get("protected_source_roots", [])]
    if any(source == p.resolve() or source.is_relative_to(p.resolve()) for p in protected):
        raise Blocked("Reference/example source is read-only")
    m = manifest_for(source)
    root.mkdir(parents=True, exist_ok=True)
    prepare_control_directories(root)
    folder = batch_folder(cfg, m)
    mp = folder / "manifest.json"
    if mp.exists():
        if mp.is_symlink() or folder.is_symlink():
            raise Blocked("Batch manifest/workspace link refused")
        old = read_json(mp)
        if batch_identity(old) != batch_identity(m):
            raise Blocked("Existing batch identity mismatch")
        m = old
    else:
        control = root / ".runtime" / "planning"
        control.mkdir(parents=True, exist_ok=True)
        with BatchLock(control):
            if mp.exists():
                m = read_json(mp)
            else:
                assign_workspaces(m, folder, root)
                m["schema_version"] = 2
                m['pipeline_profile'] = cfg.get('runner', {}).get('pipeline_profile', 'legacy')
                m['delivery_profile'] = cfg.get('runner', {}).get('delivery_profile', 'full')
                # Freeze scheduler capacity at plan time.  A later machine
                # config change must not silently alter an already registered
                # batch (especially recording concurrency and its memory
                # admission policy).
                execution = cfg.get('execution', {})
                m['execution_profile'] = {
                    key: execution.get(key, default)
                    for key, default in (
                        ('case_concurrency', 1),
                        ('review_concurrency', 1),
                        ('expedited_review_concurrency', 1),
                        ('recording_concurrency', 1),
                        ('recording_min_available_mb', 0),
                        ('recording_reserve_mb', 0),
                        ('evidence_concurrency', 1),
                        ('fair_queue', False),
                    )
                }
                atomic_json(mp, m)
    return {**m, "batch_workspace": str(folder)}


def batch_identity(m: dict) -> dict:
    copy = json.loads(json.dumps(m))
    copy.pop("schema_version", None)
    copy.pop("batch_workspace", None)
    copy.pop("workspace_month", None)
    copy.pop("pipeline_profile", None)
    copy.pop("delivery_profile", None)
    copy.pop("execution_profile", None)
    copy.pop("output_root", None)
    for entry in copy.get("cases", []):
        entry.pop("captured_at", None)
        entry.pop("workspace_name", None)
        entry.pop("workspace_relative", None)
        entry.pop("delivery_name", None)
    return copy


def validate_output_root(m: dict) -> None:
    source = Path(m["source_root"]).resolve()
    output = Path(m["output_root"])
    allowed = {source.parent / (source.name + "1"), source / "_成品"}
    if has_path_link(output) or output.resolve() not in allowed:
        raise Blocked("Output root must be the default sibling or the source _成品 directory")


def load_batch(cfg: dict, ref: str) -> tuple[dict, Path]:
    root = cfg["_root"]
    p = Path(ref)
    if p.is_dir():
        fresh = manifest_for(p)
        bid = fresh["batch_id"]
    elif len(ref) == 20 and all(c in "0123456789abcdef" for c in ref):
        bid = ref
    else:
        raise Blocked("Use planned source directory or batch ID")
    folder = inside(batch_folder(cfg, bid), root)
    if folder.is_symlink() or (folder / "manifest.json").is_symlink():
        raise Blocked("Batch manifest/workspace link refused")
    m = read_json(folder / "manifest.json")
    validate_output_root(m)
    if m["batch_id"] != bid or batch_identity(manifest_for(Path(m["source_root"]))) != batch_identity(m):
        raise Blocked("Source changed since plan; create a new plan")
    return m, folder


def apply_frozen_execution_profile(cfg: dict, manifest: dict) -> dict:
    """Return an execution copy whose scheduler settings are batch-scoped.

    Pre-profile manifests are legacy batches.  They retain the historical
    single recording slot and no memory guard; new plans carry an explicit
    profile and are replayed exactly as planned.
    """
    result = dict(cfg)
    execution = dict(cfg.get('execution', {}))
    profile = manifest.get('execution_profile')
    if profile is None:
        execution['recording_concurrency'] = 1
        execution['recording_min_available_mb'] = 0
        execution['recording_reserve_mb'] = 0
    else:
        if not isinstance(profile, dict):
            raise Blocked('Batch execution_profile is invalid; create a new plan instead of guessing scheduler limits')
        allowed = {
            'case_concurrency', 'review_concurrency', 'expedited_review_concurrency',
            'recording_concurrency', 'recording_min_available_mb',
            'recording_reserve_mb', 'evidence_concurrency', 'fair_queue',
        }
        unknown = sorted(set(profile) - allowed)
        if unknown:
            raise Blocked('Batch execution_profile contains unknown keys: ' + ', '.join(unknown))
        for key in ('case_concurrency', 'review_concurrency', 'expedited_review_concurrency', 'recording_concurrency', 'evidence_concurrency'):
            value = profile.get(key)
            if type(value) is not int or not 1 <= value <= 8:
                raise Blocked(f'Batch execution_profile.{key} must be an integer from 1 to 8')
        for key in ('recording_min_available_mb', 'recording_reserve_mb'):
            value = profile.get(key)
            if type(value) is not int or not 0 <= value <= 1024 * 1024:
                raise Blocked(f'Batch execution_profile.{key} must be a bounded non-negative integer')
        if type(profile.get('fair_queue')) is not bool:
            raise Blocked('Batch execution_profile.fair_queue must be a boolean')
        execution.update(profile)
    result['execution'] = execution
    return result


class BatchLock:
    def __init__(self, folder: Path):
        self.path = folder / "run.lock"
        self.file = None

    def __enter__(self):
        self.file = self.path.open("a+b", buffering=0)
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            winerror = getattr(exc, 'winerror', None)
            if winerror == 5 or (os.name != 'nt' and getattr(exc, 'errno', None) == 13):
                raise Blocked(f"Batch lock permission/ACL failure (winerror={winerror}, errno={getattr(exc, 'errno', None)}): {self.path}") from exc
            raise Busy(f"Batch lock contended (winerror={winerror}, errno={getattr(exc, 'errno', None)}): {self.path}") from exc
        self.file.seek(0)
        self.file.truncate()
        self.file.write(f"pid={os.getpid()} time={time.time()}\n".encode("ascii"))
        self.file.flush()
        return self

    def __exit__(self, *_):
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


@contextmanager
def stage_slot(cfg: dict, kind: str, *, owner=None, checkpoint=None):
    def recording_admission():
        if kind != 'recording':
            return
        # This is deliberately checked after the shared slot lock is owned;
        # startup preflight is only an early failure and memory can change
        # while a case waits in the fair queue.
        from runtime_doctor import recording_memory_status
        memory = recording_memory_status(cfg)
        if not memory['ok']:
            raise Blocked(f'Recording memory guard at slot admission: {memory["available_mb"]}MB effective headroom, {memory["required_mb"]}MB required; no recording process was started')

    limits = {"build": "case_concurrency", "review": "review_concurrency", "review_expedited": "expedited_review_concurrency", "recording": "recording_concurrency", "evidence": "evidence_concurrency"}
    limit = cfg.get("execution", {}).get(limits[kind], 1)
    root = cfg["_root"] / ".runtime" / "slots" / kind
    root.mkdir(parents=True, exist_ok=True)
    if cfg.get('execution', {}).get('fair_queue', False):
        from case_queue import fair_slot
        with fair_slot(root, limit, BatchLock, Busy, atomic_json, owner=owner, checkpoint=checkpoint):
            recording_admission()
            yield
        return
    acquired = None
    while acquired is None:
        if checkpoint:
            checkpoint()
        for index in range(limit):
            directory = root / str(index)
            directory.mkdir(exist_ok=True)
            lock = BatchLock(directory)
            try:
                lock.__enter__()
            except Busy:
                continue
            acquired = lock
            break
        if acquired is None:
            time.sleep(0.1)
    try:
        if checkpoint:
            checkpoint()
        recording_admission()
        yield
    finally:
        acquired.__exit__(None, None, None)


def allocate_resources(cfg: dict, m: dict, folder: Path, *, entries=None) -> dict:
    """Allocate only the selected cases and preserve existing resource rows."""
    entries = list(m['cases'] if entries is None else entries)
    directory = cfg["_root"] / ".runtime" / "ports"
    directory.mkdir(parents=True, exist_ok=True)
    registry = directory / "leases.json"
    with BatchLock(directory):
        leases = read_json(registry) if registry.exists() else {}
        if (not isinstance(leases, dict) or any(
                not isinstance(key, str) or not isinstance(ports, list) or len(ports) != 4 or
                any(type(p) is not int or not 18000 <= p < 49000 for p in ports)
                for key, ports in leases.items())):
            raise Blocked('Invalid port lease registry; preserve it for repair instead of reallocating live case ports')
        all_ports = [p for ports in leases.values() for p in ports]
        if len(all_ports) != len(set(all_ports)):
            raise Blocked('Duplicate port lease detected; live case ownership needs verification')
        used = {p for ports in leases.values() for p in ports}
        for entry in entries:
            key = m["batch_id"] + ":" + entry["case_id"]
            if key in leases:
                continue
            ports = []
            for port in range(18000, 49000):
                if port in used:
                    continue
                with socket.socket() as probe:
                    try:
                        if os.name == "nt":
                            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                        probe.bind(("127.0.0.1", port))
                    except OSError:
                        continue
                ports.append(port)
                used.add(port)
                if len(ports) == 4:
                    break
            if len(ports) != 4:
                raise Blocked("No free local ports for case resources")
            leases[key] = ports
        atomic_json(registry, leases)
    resources_path = folder / "resources.json"
    result = read_json(resources_path) if resources_path.is_file() else {}
    result = dict(result)
    for entry in entries:
        case = case_workspace(folder, entry)
        result[entry["case_id"]] = {"ports": leases[m["batch_id"] + ":" + entry["case_id"]],
                                  "browser_profile": str(case / ".runtime" / "browser"),
                                  "temp_dir": str(case / ".runtime" / "tmp")}
    atomic_json(resources_path, result)
    return result


def native_codex(cfg: dict) -> Path:
    override = cfg["runner"].get("codex_executable")
    candidates = [Path(override)] if override else []
    found = shutil.which("codex.exe")
    if found:
        candidates.append(Path(found))
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
        candidates.extend(sorted(local.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True))
        npm_root = Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/@openai'
        candidates.extend(npm_root.glob('codex*/vendor/*/codex/codex.exe'))
        candidates.extend(npm_root.glob('codex/node_modules/@openai/codex*/vendor/*/codex/codex.exe'))
    for p in candidates:
        if p.is_file() and p.suffix.lower() == ".exe":
            return p.resolve()
    raise Blocked("Native codex.exe not found; .cmd launcher is not executed")


def model_for_stage(cfg: dict, stage: str) -> dict:
    if stage.startswith('review_'):
        return cfg['models']['reviewer']
    if stage.startswith('repair_') or stage == 'prepare_video':
        # Omitted repairer retains compatibility with archived configurations.
        # The current configuration explicitly separates ultra repair from high build.
        return cfg['models'].get('repairer', cfg['models']['builder'])
    return cfg['models']['builder']


def command_for(cfg: dict, case: Path, stage: str, output: Path | None = None, *, dry_run: bool = False) -> list[str]:
    review = stage in {"review_visual", "review_video", "review_final"}
    model = model_for_stage(cfg, stage)
    approval_mode = cfg["runner"].get("worker_approval_mode", "never")
    if approval_mode not in {"never", "auto_review"}:
        raise Blocked("worker_approval_mode must be never or auto_review")
    # Auto-review retains workspace-write and independently reviews each
    # eligible escalation. It must never be combined with approval_policy=never.
    approval = (["--approve-for-me"] if not review and approval_mode == "auto_review"
                else ["--config", "approval_policy=never"])
    # The native CLI makes --approve-for-me mutually exclusive with --sandbox;
    # that supported flag itself selects workspace-write.
    sandbox = ([] if not review and approval_mode == "auto_review" else
               ["--sandbox", "read-only" if review else "workspace-write"])
    command = [str(cfg["runner"].get("codex_executable") or "codex.exe") if dry_run else str(native_codex(cfg)), "exec", "--model", model["model"], "--config", f"model_reasoning_effort={model['reasoning_effort']}",
               *approval, "--json", "--skip-git-repo-check", *sandbox, "-C", str(case)]
    if review:
        assert output is not None
        command += ["--output-schema", str(review_schema(cfg)), "-o", str(output)]
    return command + ["-"]


def review_schema(cfg: dict) -> Path:
    target = Path(__file__).resolve().parent.parent / "schemas" / "review-response.schema.json"
    if not target.is_file():
        raise Blocked(f"Review schema missing: {target}")
    return target


def snapshot(case: Path, *, video: bool) -> dict[str, str]:
    result = {}
    live_streams = set()
    stream_registry = case / 'evidence/runtime-streams.json'
    if stream_registry.is_file():
        streams = read_json(artifact(case, 'evidence/runtime-streams.json'))
        if streams.get('purpose') != 'live_service_output' or not isinstance(streams.get('paths'), list):
            raise Blocked('Invalid runtime stream registry')
        manifest = read_json(artifact(case, 'evidence/artifact-manifest.json')) if (case / 'evidence/artifact-manifest.json').is_file() else {}
        def declared_strings(value):
            if isinstance(value, str):
                yield value.replace('\\', '/')
            elif isinstance(value, dict):
                for child in value.values():
                    yield from declared_strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from declared_strings(child)
        declared = set(declared_strings(manifest))
        for relative in streams['paths']:
            if not isinstance(relative, str) or not re.fullmatch(r'evidence/service-[0-9-]+-(stdout|stderr)\.log', relative):
                raise Blocked('Runtime stream exclusion is limited to service stdout/stderr logs')
            inside(case / relative, case, must_exist=True)
            if relative in declared:
                raise Blocked('Declared artifact cannot be excluded as a runtime stream')
            live_streams.add(relative)
    excluded = {"node_modules", ".venv", "venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".runtime"}
    for directory, dirs, names in os.walk(case, followlinks=False):
        parent = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in excluded)
        for d in dirs:
            linked = parent / d
            if has_path_link(linked):
                raise Blocked(f"Snapshot directory link refused: {linked}")
        if parent == case:
            dirs[:] = [d for d in dirs if d != "logs" and (video or d != "recording")]
        if not video and parent == case / "evidence":
            dirs[:] = [d for d in dirs if d != "video"]
        for name in sorted(names):
            path = parent / name
            rel = path.relative_to(case).as_posix()
            if rel in live_streams:
                continue
            if not video and rel == "evidence/review_video.json":
                continue
            if path.is_symlink():
                raise Blocked(f"Snapshot file link refused: {path}")
            inside(path, case, must_exist=True)
            # Empty source files such as __init__.py are valid. Required evidence
            # is checked separately by artifact(), where emptiness is an error.
            result[rel] = sha256(path)
    # Worker streams remain excluded, but a completed test's declared output is
    # required review evidence even when it lives under logs/ (or another pruned
    # directory). Use the same path/emptiness guards as manifest validation.
    manifest_path = case / "evidence" / "artifact-manifest.json"
    if manifest_path.is_file():
        manifest = read_json(artifact(case, "evidence/artifact-manifest.json"))
        report_name = manifest.get("test_report") if isinstance(manifest, dict) else None
        if isinstance(report_name, str):
            report_path = artifact(case, report_name)
            result[report_name] = sha256(report_path)
            report = read_json(report_path)
            for test in report.get("tests", []) if isinstance(report, dict) else []:
                if isinstance(test, dict) and isinstance(test.get("log"), str):
                    result[test["log"]] = sha256(artifact(case, test["log"]))
    return result


def snapshot_id(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def review_request(files: dict[str, str], required: set[str]) -> dict:
    return {"protocol": "evidence-ids-v1", "review_id": snapshot_id(files)[:16],
            "evidence": {f"E{i:03d}": p for i, p in enumerate(sorted(required), 1)}}


def bind_review_response(raw: dict, request: dict, files: dict[str, str], required: set[str], manifest: dict, *, pipeline_profile='legacy') -> dict:
    """Bind the reviewer's explicit evidence selection; never infer a verdict or coverage."""
    fields = {'protocol', 'review_id', 'verdict', 'issues', 'chart_reviews', 'reviewed_evidence', 'coverage', 'limitations'}
    if not isinstance(raw, dict) or set(raw) != fields or raw['protocol'] != 'evidence-ids-v1' or raw['review_id'] != request['review_id']:
        raise Blocked('Review response does not match this evidence request')
    index = request['evidence']
    def paths(ids):
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in index for i in ids) or len(set(ids)) != len(ids):
            raise Blocked('Review contains unknown or duplicate evidence IDs')
        return [index[i] for i in ids]
    reviewed = paths(raw['reviewed_evidence'])
    if raw['verdict'] != 'revise' and not required.issubset(reviewed):
        missing = [f'{key}={path}' for key, path in index.items() if path in required and path not in reviewed]
        raise Blocked('Review omits required evidence: ' + '; '.join(missing))
    if not isinstance(raw['chart_reviews'], list):
        raise Blocked('Invalid per-chart response')
    by_id = {c['figure_id']: c for c in manifest['charts']}
    charts = []
    for row in raw['chart_reviews']:
        if not isinstance(row, dict) or set(row) != {'figure_id', 'checks', 'evidence_ids'} or row['figure_id'] not in by_id:
            raise Blocked('Review contains unknown chart')
        chart = by_id[row['figure_id']]
        charts.append({'figure_id': row['figure_id'], 'png': chart['png'], 'png_sha256': files[chart['png']],
                       'checks': row['checks'], 'evidence_files': paths(row['evidence_ids'])})
    report = {k: raw[k] for k in ('verdict', 'issues', 'coverage', 'limitations')}
    report.update(rules_version=CHART_RULES_VERSION, chart_reviews=charts, snapshot_sha256=snapshot_id(files),
                  reviewed_files=[{'path': p, 'sha256': files[p]} for p in reviewed])
    review_outcome(report, files, required, manifest=manifest, pipeline_profile=pipeline_profile)
    return report


def review_brief(report):
    if not isinstance(report, dict):
        return report
    return {k: report[k] for k in ('verdict', 'issues', 'chart_reviews', 'coverage', 'limitations', 'rules_version') if k in report}


def recording_inputs(case: Path, *, pipeline_profile='legacy') -> dict:
    """Track browser-facing changes, excluding Word, provenance, tests and old capture evidence."""
    if pipeline_profile == 'deliverable-first-v1' and (case / 'evidence/capture-plan.json').is_file():
        from capture_runner import scene_dependencies, CaptureError
        plan = read_json(artifact(case, 'evidence/capture-plan.json'))
        if plan.get('schema_version') != 2:
            raise Blocked('Output-focused recording requires capture plan schema 2')
        try:
            result = scene_dependencies(case, plan, check_hashes=False)
        except CaptureError as exc:
            raise Blocked(str(exc)) from exc
        # Replacing proof screenshots or Word-only figures cannot change the video.
        # Page inputs, routes/actions and serving identity still invalidate it.
        selection = {k: plan.get(k) for k in ('schema_version', 'case_id', 'base_url',
                                             'health_path', 'version', 'modules')}
        result['@capture-selection'] = hashlib.sha256(json.dumps(
            selection, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        return result
    manifest = read_json(artifact(case, 'evidence/artifact-manifest.json'))
    named = set(manifest.get('ui_screenshots', [])) | {c['png'] for c in manifest.get('charts', [])}
    # Generated screenshots/charts plus application sources/data. Changes conservatively re-record.
    ignored = {'source', 'evidence', 'recording', 'deliverable', 'exports', 'logs', 'tests', 'scripts'}
    result = {p: sha256(artifact(case, p)) for p in named}
    for directory, dirs, names in os.walk(case, followlinks=False):
        parent = Path(directory)
        dirs[:] = [d for d in dirs if d not in {'.runtime', '.git', '.venv', 'venv', 'node_modules', '__pycache__', '.cache', '.pytest_cache'} and (parent != case or d not in ignored)]
        for name in names:
            p = parent / name
            # Caseflow's own environment diagnostic is coordination metadata;
            # its readiness/probe updates do not change the browser application.
            if parent == case and name == '.caseflow-environment.json':
                continue
            if p.suffix.lower() in {'.py', '.js', '.mjs', '.ts', '.tsx', '.jsx', '.css', '.html', '.json', '.csv', '.db', '.sqlite', '.sqlite3', '.png', '.jpg', '.jpeg', '.svg', '.woff', '.woff2'}:
                rel = p.relative_to(case).as_posix()
                if p.is_symlink():
                    raise Blocked(f'Recording input link refused: {rel}')
                result[rel] = sha256(inside(p, case, must_exist=True))
    return result


def current_video_hash(case: Path) -> str | None:
    """Return the recorded artifact hash, or None before a usable video exists."""
    manifest_path = case / 'evidence/artifact-manifest.json'
    if not manifest_path.is_file():
        return None
    rel = read_json(manifest_path).get('video')
    if not isinstance(rel, str) or not rel:
        return None
    path = case / rel
    if not path.is_file():
        return None
    return sha256(artifact(case, rel))


CHART_RULES_VERSION = "2026-09-24"
CHART_CHECKS = {"meaning", "data", "legibility", "layout", "explanation"}
REJECTED_CHART_FILE = Path(__file__).resolve().parent.parent / "rules" / "rejected-chart-versions.json"
PROFESSIONAL_CHART_SCOPE = Path(__file__).resolve().parent.parent / "rules" / "chart-professional-scope.json"
LEGEND_CHART_SCOPE = Path(__file__).resolve().parent.parent / "rules" / "chart-legend-scope.json"


def verify_review(report: dict, files: dict[str, str], required: set[str], *, manifest: dict | None = None, pipeline_profile='legacy') -> str:
    if not isinstance(report, dict) or set(report) != {"verdict", "issues", "reviewed_files", "snapshot_sha256", "coverage", "limitations", "rules_version", "chart_reviews"}:
        raise Blocked("Unexpected review fields")
    if report['rules_version'] != CHART_RULES_VERSION:
        raise Blocked("Review uses outdated chart rules")
    if not isinstance(report["coverage"], str) or not report["coverage"].strip() or not isinstance(report["limitations"], list) or any(not isinstance(x, str) for x in report["limitations"]):
        raise Blocked("Review coverage or limitations missing")
    verdict = report.get("verdict")
    if verdict not in {"pass", "revise", "blocked"} or not isinstance(report.get("issues"), list):
        raise Blocked("Invalid review schema")
    if any(not isinstance(i, dict) or not all(isinstance(i.get(k), str) and i[k].strip() for k in ("severity", "artifact", "evidence", "fix")) for i in report["issues"]):
        raise Blocked("Invalid review issue")
    if verdict != "pass" and not report["issues"]:
        raise Blocked("Rejected review must describe issues")
    if any(i["severity"] not in {"blocker", "major", "minor"} for i in report["issues"]):
        raise Blocked("Invalid review severity")
    if verdict == "pass" and any(i["severity"] in {"blocker", "major"} for i in report["issues"]):
        raise Blocked("Passing review contains unresolved blocking issues")
    if report.get("snapshot_sha256") != snapshot_id(files):
        raise Blocked("Review snapshot does not match current artifacts")
    rows = report.get("reviewed_files")
    if not isinstance(rows, list) or any(not isinstance(r, dict) or set(r) != {"path", "sha256"} or not all(isinstance(v, str) for v in r.values()) for r in rows):
        raise Blocked("Invalid reviewed-files array")
    reviewed = {r["path"]: r["sha256"] for r in rows}
    if len(reviewed) != len(rows) or not required.issubset(reviewed):
        raise Blocked("Review omits required evidence")
    for rel, digest in reviewed.items():
        if files.get(rel) != digest:
            raise Blocked(f"Review contains stale/wrong hash: {rel}")
    chart_reviews = report['chart_reviews']
    if not isinstance(chart_reviews, list):
        raise Blocked("Missing per-chart reviews")
    expected = {c['figure_id']: c for c in (manifest or {}).get('charts', [])}
    seen = set()
    for row in chart_reviews:
        if not isinstance(row, dict) or set(row) != {'figure_id', 'png', 'png_sha256', 'checks', 'evidence_files'}:
            raise Blocked("Invalid per-chart review")
        fid = row['figure_id']
        if not isinstance(fid, str) or fid in seen or (manifest is not None and fid not in expected):
            raise Blocked("Review must cover every chart exactly once")
        seen.add(fid)
        if not isinstance(row['png'], str) or reviewed.get(row['png']) != row['png_sha256'] or not row['png_sha256']:
            raise Blocked("Chart review has missing/stale PNG evidence")
        checks = row['checks']
        if not isinstance(checks, dict) or set(checks) != CHART_CHECKS:
            raise Blocked("Chart review omits required quality criteria")
        for check in checks.values():
            if not isinstance(check, dict) or set(check) != {'passed', 'evidence'} or type(check['passed']) is not bool or not isinstance(check['evidence'], str) or not check['evidence'].strip():
                raise Blocked("Invalid chart criterion evidence")
        if verdict == 'pass' and not all(c['passed'] for c in checks.values()):
            raise Blocked("Passing review contains failed chart criteria")
        evidence = row['evidence_files']
        if not isinstance(evidence, list) or not evidence or any(not isinstance(p, str) or p not in reviewed for p in evidence):
            raise Blocked("Chart review evidence must be reviewed current files")
        if manifest is not None:
            chart = expected[fid]
            if row['png'] != chart['png'] or not {chart[k] for k in ('png', 'csv', 'explanation')}.issubset(evidence):
                raise Blocked("Chart review omits PNG/CSV/explanation")
            if not set(evidence).intersection(manifest['rendered_pages']):
                raise Blocked("Chart review omits normal-size Word evidence")
            if pipeline_profile != 'deliverable-first-v1' and not set(evidence).intersection(manifest['ui_screenshots']):
                raise Blocked("Chart review omits normal-size UI/Word evidence")
    if manifest is not None and seen != set(expected):
        raise Blocked("Review must cover every chart exactly once")
    return verdict


def review_outcome(report: dict, files: dict[str, str], required: set[str], *, manifest: dict, pipeline_profile='legacy') -> tuple[str, str | None]:
    """Incomplete rejection can guide repair, but can never certify delivery."""
    try:
        return verify_review(report, files, required, manifest=manifest, pipeline_profile=pipeline_profile), None
    except Blocked as exc:
        warning = str(exc)
        if (not isinstance(report, dict) or report.get('verdict') != 'revise' or
                not (warning == 'Review omits required evidence' or warning.startswith('Review contains stale/wrong hash: '))):
            raise
        # Check all remaining structural/chart rules without adding a single
        # unreported file. The original report is neither overwritten nor signed.
        advisory = deepcopy(report)
        rows = advisory.get('reviewed_files', [])
        for row in rows:
            if isinstance(row, dict) and row.get('path') in files:
                row['sha256'] = files[row['path']]
        declared = {r['path'] for r in rows}
        if verify_review(advisory, files, required & declared, manifest=manifest, pipeline_profile=pipeline_profile) != 'revise':
            raise
        return 'revise', warning


VISIBLE_COPY_VERSION = "2026-09-23"
VISIBLE_FORBIDDEN = ("专利", "权利要求", "权要", "模拟", "虚拟", "仿真", "工程样本", "工程示例", "演示数据", "推演数据", "合成数据")


def visible_copy_hits(text: str) -> list[str]:
    compact = re.sub(r"[\s\u200b-\u200d\ufeff]+", "", text)
    hits = [term for term in VISIBLE_FORBIDDEN if term in compact]
    hits += re.findall(r"\b(?:mock|dummy|synthetic|simulated|simulation|virtual|demo(?:nstration)?[\s-]+data)\b", text, re.I)
    return sorted(set(hits))


def validate_visible_copy(case: Path, a: dict) -> set[str]:
    if a.get("readme") != "README.md":
        raise Blocked("Data origin and unverified scope must be recorded in README.md; manifest readme is required")
    artifact(case, "README.md")
    audit_path = a.get("ui_text_audit")
    if not isinstance(audit_path, str):
        raise Blocked("Missing ui_text_audit; capture actual visible text alongside each UI screenshot")
    audit = read_json(artifact(case, audit_path))
    if audit.get("rules_version") != VISIBLE_COPY_VERSION or not isinstance(audit.get("pages"), list) or not audit['pages']:
        raise Blocked("UI text audit missing current rules version or pages")
    seen = set()
    for row in audit['pages']:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in ('url', 'state', 'visible_text', 'screenshot', 'screenshot_sha256')):
            raise Blocked("UI text audit requires url/state/visible_text/screenshot/hash for every captured state")
        rel = row['screenshot']
        if rel not in a.get('ui_screenshots', []) or sha256(artifact(case, rel)) != row['screenshot_sha256']:
            raise Blocked("UI text audit screenshot missing or stale")
        hits = visible_copy_hits(row['visible_text'])
        if hits:
            raise Blocked(f"Forbidden visible web text at {row['url']} ({row['state']}): {', '.join(hits)}; move origin/limitations to README.md")
        seen.add(rel)
    if seen != set(a.get('ui_screenshots', [])):
        raise Blocked("UI text audit does not cover every current UI screenshot")
    return {"README.md", audit_path}


def contact_sample_coverage(frames: list, sheets: list) -> set[str]:
    """Only explicit, complete parent-generated sheet membership replaces sample opens."""
    if not any('frame_files' in sheet for sheet in sheets):
        return set()  # Legacy evidence has no provable membership.
    if any(not isinstance(sheet.get('frame_files'), list) or not sheet['frame_files'] for sheet in sheets):
        raise Blocked('Incomplete contact sheet membership')
    members = [p for sheet in sheets for p in sheet['frame_files']]
    expected = [frame['file'] for frame in frames]
    if any(not isinstance(p, str) for p in members) or members != expected or len(set(members)) != len(members):
        raise Blocked('Contact sheets do not cover the exact ordered timeline')
    return {frame['file'] for frame in frames if frame.get('type') == 'uniform_sample'}


def validate_build_contract(case: Path, source_hash: str) -> tuple[dict, set[str]]:
    """Shared cheap contract: usable before parent-owned rendering or recording."""
    ap = artifact(case, "evidence/artifact-manifest.json")
    a = read_json(ap)
    if a.get("source_sha256") != source_hash:
        raise Blocked("Artifact source hash mismatch")
    required = {"evidence/artifact-manifest.json"}
    def add(value: str, kind: str | None = None) -> Path:
        p = artifact(case, value)
        if kind == "image" and not good_image(p):
            raise Blocked(f"Invalid image: {value}")
        if kind == "docx" and not good_docx(p):
            raise Blocked(f"Invalid DOCX: {value}")
        required.add(value)
        return p
    add(a["revised_docx"], "docx")
    charts = a.get("charts")
    if not isinstance(charts, list):
        raise Blocked("Missing charts inventory")
    if len(charts) < 2:
        raise Blocked("Each case requires at least two meaningful charts; formula count does not determine chart count")
    ids, images = set(), set()
    rejected = read_json(REJECTED_CHART_FILE).get('versions', []) if REJECTED_CHART_FILE.is_file() else []
    rejected_hashes = {item['sha256']: item for item in rejected}
    for chart in charts:
        if not isinstance(chart, dict) or not chart.get("figure_id") or not chart.get("snapshot_id") or not isinstance(chart.get("formula_ids"), list):
            raise Blocked("Incomplete chart trace")
        digest = sha256(add(chart["png"], "image"))
        if digest in rejected_hashes:
            raise Blocked(f"Explicitly rejected chart version must be replaced: {chart['png']}; {rejected_hashes[digest]['reason']}")
        if chart['figure_id'] in ids or digest in images:
            raise Blocked("Duplicate chart cannot count as another figure")
        ids.add(chart['figure_id'])
        images.add(digest)
        if not good_csv(add(chart["csv"])):
            raise Blocked("CSV lacks header or data row")
        add(chart["explanation"])
    if not isinstance(a.get('chart_design'), str):
        raise Blocked("Missing chart_design: explain the business question and figure selection before review")
    design = read_json(add(a['chart_design']))
    if not isinstance(design, dict) or design.get('rules_version') != CHART_RULES_VERSION or not isinstance(design.get('figures'), list):
        raise Blocked("chart_design missing current rules version or figures")
    quality_addenda = design.get('quality_addenda', [])
    professional = isinstance(quality_addenda, list) and '2026-09-28-professional-charts' in quality_addenda
    if professional and len(charts) > 6:
        raise Blocked("Professional chart set cannot exceed six independent result figures")
    plans = design['figures']
    if any(not isinstance(p, dict) or not isinstance(p.get('figure_id'), str) for p in plans) or len(plans) != len(charts) or {p['figure_id'] for p in plans} != ids:
        raise Blocked("chart_design must cover every chart exactly once")
    by_id = {p['figure_id']: p for p in plans}
    errors = []
    for chart in charts:
        item = by_id[chart['figure_id']]
        prefix = f"chart_design[{chart['figure_id']}]"
        for key in ('business_question', 'reader_takeaway', 'chart_type', 'selection_reason', 'scenario_coverage', 'calculation_basis'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append(f'{prefix}.{key}: expected nonempty string, got {type(item.get(key)).__name__}')
        sections = item.get('explanation_outline')
        for key in ('purpose', 'reading', 'calculation', 'findings', 'decision'):
            if not isinstance(sections, dict) or not isinstance(sections.get(key), str) or not sections[key].strip():
                errors.append(f'{prefix}.explanation_outline.{key}: expected nonempty string')
        if any(item.get(k + '_sha256') != sha256(artifact(case, chart[k])) for k in ('png', 'csv', 'explanation')):
            errors.append(f'{prefix}: stale PNG/CSV/explanation hashes')
        if professional:
            chart_type = item.get('chart_type', '').casefold()
            forbidden = ('示意', '流程图', '架构图', '概念图', '关系图', '真值表', '卡片', '色块',
                         'flowchart', 'architecture diagram', 'concept diagram', 'truth table')
            if any(term in chart_type for term in forbidden):
                errors.append(f'{prefix}.chart_type: professional result charts cannot be diagrammatic or placeholder types')
    if errors:
        raise Blocked('; '.join(errors))
    for key in ("formula_registry", "source_trace"):
        if not read_json(add(a[key])):
            raise Blocked(f"Empty source audit: {key}")
    return a, required


def validate_manifest(case: Path, source_hash: str, *, video: bool, cfg: dict) -> tuple[dict, set[str]]:
    a, required = validate_build_contract(case, source_hash)
    def add(value: str, kind: str | None = None) -> Path:
        p = artifact(case, value)
        if kind == 'image' and not good_image(p):
            raise Blocked(f'Invalid image: {value}')
        required.add(value)
        return p
    for key in ("ui_screenshots", "rendered_pages"):
        arr = a.get(key)
        if not isinstance(arr, list) or not arr:
            raise Blocked(f"Missing {key}")
        if len({x.casefold() for x in arr}) != len(arr):
            raise Blocked(f"Repeated {key}")
        for name in arr:
            add(name, "image")
    if cfg.get("runner", {}).get("require_ui_text_audit", False):
        required.update(validate_visible_copy(case, a))
    report = read_json(add(a["test_report"]))
    if not isinstance(report, dict) or not report.get("tests") or not isinstance(report["tests"], list):
        raise Blocked("Empty test report")
    if any(not isinstance(x, dict) or not x.get("command") or not isinstance(x.get("exit_code"), int) for x in report["tests"]):
        raise Blocked("Invalid test record")
    if any(x["exit_code"] != 0 for x in report["tests"]):
        raise Blocked("Test report contains failed command")
    for test in report["tests"]:
        add(test["log"])
    if report.get("source_sha256") != source_hash:
        raise Blocked("Test report source hash mismatch")
    if report.get("rendered_docx_sha256") != sha256(artifact(case, a["revised_docx"])):
        raise Blocked("Render evidence does not match revised DOCX")
    if report.get("rendered_page_count") != len(a["rendered_pages"]):
        raise Blocked("Rendered page count mismatch")
    preservation = read_json(add(a["preservation_report"]))
    # Historical reports keep their frozen protocol. Newly generated reports
    # explicitly check placement; a failed check cannot be accepted or exported.
    if preservation.get("all_requested_figures_at_document_end") is False:
        raise Blocked("New Word figures/captions are not at document end")
    if preservation.get("all_requested_figures_referenced_in_body") is False:
        raise Blocked("New Word figure reference missing from body explanation")
    if preservation.get("original_sha256") != source_hash or preservation.get("revised_sha256") != report["rendered_docx_sha256"] or not preservation.get("structural_preservation_ok") or not preservation.get("all_requested_figures_embedded"):
        raise Blocked("Word preservation evidence failed or stale")
    render = read_json(add(a["render_report"]))
    expected_pages = {p: sha256(artifact(case, p)) for p in a["rendered_pages"]}
    if render.get("docx_sha256") != report["rendered_docx_sha256"] or render.get("page_count") != len(expected_pages) or render.get("page_hashes") != expected_pages:
        raise Blocked("Render page hashes differ")
    if sha256(add(render["pdf"])) != render.get("pdf_sha256"):
        raise Blocked("Render PDF changed")
    if video:
        vid = add(a["video"])
        if not good_mp4(vid):
            raise Blocked("Invalid MP4 signature")
        sheets = a.get("video_contact_sheets")
        if not isinstance(sheets, list) or not sheets:
            raise Blocked("Missing video contact sheets")
        for x in sheets:
            add(x, "image")
        timeline = read_json(add(a["video_timeline"]))
        if timeline.get("video_sha256") != sha256(vid) or not timeline.get("decode_ok"):
            raise Blocked("Video timeline invalid or stale")
        duration = float(timeline.get("duration", 0))
        video_cfg = cfg["video"]
        if not video_cfg["min_seconds"] <= duration <= video_cfg["max_seconds"]:
            raise Blocked("Video duration out of range")
        if timeline.get("width") != video_cfg["width"] or timeline.get("height") != video_cfg["height"]:
            raise Blocked("Video dimensions wrong")
        if timeline.get("codec") != "h264" or not math.isfinite(float(timeline.get("fps", 0))) or abs(float(timeline.get("fps", 0)) - video_cfg["fps"]) > .5:
            raise Blocked("Video codec/fps wrong")
        frames = timeline.get("frames")
        if not isinstance(frames, list) or len(frames) < int(duration * video_cfg["sample_fps"]) - 1:
            raise Blocked("Incomplete video frames")
        samples = sorted(float(x.get("seconds", -1)) for x in frames if isinstance(x, dict) and x.get("type") == "uniform_sample")
        if len(samples) < math.floor(duration * video_cfg["sample_fps"]) - 1 or not samples or samples[0] > .05 or samples[-1] < duration - 1 / video_cfg["sample_fps"] - .05 or any(b - a > 1 / video_cfg["sample_fps"] + .06 for a, b in zip(samples, samples[1:])):
            raise Blocked("Timeline sampling has gaps")
        seconds = [float(x.get("seconds", -1)) for x in frames if isinstance(x, dict)]
        if len(seconds) != len(frames) or any(not math.isfinite(x) for x in seconds) or min(seconds, default=999) > 0.21 or max(seconds, default=-1) < duration - 1 / video_cfg["sample_fps"] - .05:
            raise Blocked("Video first or final frame missing")
        if not {"first", "last"}.issubset({x.get("type") for x in frames}):
            raise Blocked("Explicit first and last frames missing")
        if min(x["seconds"] for x in frames if x.get("type") == "first") > .05 or max(x["seconds"] for x in frames if x.get("type") == "last") < duration - 1 / video_cfg["fps"] - .05:
            raise Blocked("Terminal video frame missing")
        if len({x.get("file") for x in frames}) != len(frames):
            raise Blocked("Duplicate timeline frame paths")
        if not timeline.get("contact_sheets"):
            raise Blocked("Timeline contact sheets missing")
        if set(sheets) != {Path(x.get("file", "")).relative_to(case).as_posix() if Path(x.get("file", "")).is_absolute() else x.get("file") for x in timeline["contact_sheets"]}:
            raise Blocked("Manifest and timeline contact sheets differ")
        covered_samples = contact_sample_coverage(frames, timeline['contact_sheets'])
        for item in frames + timeline.get("contact_sheets", []):
            raw = item.get("file")
            p = Path(raw)
            if not p.is_absolute():
                p = case / raw
            p = inside(p, case, must_exist=True)
            if not good_image(p) or sha256(p) != item.get("sha256"):
                raise Blocked("Bad timeline image hash")
            if raw not in covered_samples:
                required.add(p.relative_to(case).as_posix())
        # Direct probe verifies the actual MP4, not solely the producer's JSON.
        probe = subprocess.run([cfg.get("runtime", {}).get("ffprobe", "ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration:stream=codec_name,width,height,avg_frame_rate", "-of", "json", str(vid)],
                                capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        probed = json.loads(probe.stdout)
        streams = probed.get("streams") or []
        if not streams:
            raise Blocked("FFprobe found no video stream")
        stream = streams[0]
        if abs(float(probed["format"]["duration"]) - duration) > .05:
            raise Blocked("FFprobe duration disagrees with timeline")
        if stream.get("codec_name") != "h264" or stream.get("width") != video_cfg["width"] or stream.get("height") != video_cfg["height"]:
            raise Blocked("FFprobe codec/dimensions invalid")
        num, den = (float(x) for x in stream.get("avg_frame_rate", "0/1").split("/"))
        if not den or abs(num / den - video_cfg["fps"]) > .5:
            raise Blocked("FFprobe frame rate invalid")
    return a, required


def prompt(cfg: dict, stage: str, context: dict) -> str:
    context = dict(context)
    context['project_root'] = str(Path(__file__).resolve().parents[1])
    context['runtime'] = cfg.get('runtime', {})
    stem = {"build": "build", "repair_visual": "repair", "review_visual": "review_visual",
            "video": "video", "repair_video": "repair", "review_video": "review_video",
            "review_final": "review_final", "repair_final": "repair", "prepare_video": "prepare_video"}[stage]
    prompt_root = cfg["_prompts"]
    if context.get('pipeline_profile') == 'deliverable-first-v1':
        prompt_root = prompt_root / 'deliverable-first'
        if stage.startswith('review_'):
            stem = 'review_final'
    body = (prompt_root / f"{stem}.md").read_text(encoding="utf-8")
    copy_rule = Path(__file__).resolve().parent.parent / "rules" / "web-visible-copy.md"
    if copy_rule.is_file():
        body += "\n\n" + copy_rule.read_text(encoding="utf-8")
    body += "\n\n" + (Path(__file__).resolve().parent.parent / "rules" / "chart-quality.md").read_text(encoding="utf-8")
    chart_scope = read_json(PROFESSIONAL_CHART_SCOPE)
    if context.get("batch_id") and context["batch_id"] not in chart_scope["existing_batch_ids"]:
        body += "\n\n" + PROFESSIONAL_CHART_SCOPE.with_name("chart-professional.md").read_text(encoding="utf-8")
        context["chart_policy_addendum"] = chart_scope["version"]
    legend_scope = read_json(LEGEND_CHART_SCOPE)
    if context.get('batch_id') and context['batch_id'] not in legend_scope['existing_batch_ids']:
        body += '\n\n' + LEGEND_CHART_SCOPE.with_name('chart-legend.md').read_text(encoding='utf-8')
        context['legend_policy_addendum'] = legend_scope['version']
    if not stage.startswith("review_"):
        body += "\n\n" + (Path(__file__).resolve().parent.parent / "rules" / "worker-environment.md").read_text(encoding="utf-8")
    body += "\n\n" + (Path(__file__).resolve().parent.parent / "rules" / "material-sourcing.md").read_text(encoding="utf-8")
    if context.get('pipeline_profile') == 'efficient-v1' and not stage.startswith('review_'):
        body += '\n\n' + (Path(__file__).resolve().parent.parent / 'rules' / 'efficient-pipeline.md').read_text(encoding='utf-8')
    if context.get('delivery_profile') == 'word-video':
        body += '\n\n用户2026-09-28成品规则（2026-09-30再次明确目录层级）：本批每案根目录放修订Word，视频放本案“模拟系统”子目录，禁止Word与MP4平铺；图表资料、原始文件、README不复制到成品。上述资料在案件工作区完整保留，继续生成、校验和独立审查。其他规则中的随成品交付README或原件等旧表述对此批不适用。父执行器统一发布，worker不得自行删证据或修改成品目录。'
    for key in ('visual_review', 'video_review', 'final_review', 'review'):
        if key in context:
            context[key] = review_brief(context[key])
    if stage.startswith('review_') and context.get('review_request'):
        for key in ('snapshot_files', 'snapshot_sha256', 'required_review_files'):
            context.pop(key, None)
        body = '\n'.join(line for line in body.splitlines() if not line.startswith(('只返回', '提交前逐字符', '返回字段必须', '2026-09-24协议更新')))
        body += '\n\n输出必须使用review-response.schema.json的evidence-ids-v1协议。只返回review_id、protocol、verdict、issues、chart_reviews、reviewed_evidence、coverage、limitations八字段。reviewed_evidence和每图evidence_ids填写review_request.evidence中的短ID，不抄写SHA256或长路径列表，不输出旧版reviewed_files/snapshot_sha256/png_sha256。父执行器核对审查前后文件未变，再绑定哈希，保留原始答复。必须实际审查当前全部必要证据，覆盖方式在coverage中明确；不得把声明IDs当成看过。'
        body += '\n受控timeline若含完整frame_files映射，均匀采样画面通过全部接触页审查，reviewed_evidence只登记实际看的接触页ID，不声称逐个打开原帧。全部原帧仍由父执行器逐个验证哈希；真实首尾帧、交互前后关键原帧和疑点原帧仍须打开。coverage明确本次查看方式。旧timeline无映射时不推定覆盖。revise证据清单不全可作为返修意见，但不能签通过；pass必须覆盖全部当前必要ID。'
        body += '\n提交pass前，用context.runtime.python运行共享scripts/review_check.py "context.review_request_path" --ids 后跟本次实际检查或合法沿用的全部短ID，先核对遗漏/重复/未知ID。程序只检查清单，不证明已阅，也不补齐ID。PDF与其PNG页是不同证据：PDF需读取页数/文档完整性并核对受控render绑定；全页视觉可由当前PNG完成。复验可沿用此前真正核验且哈希未变的PDF，不重复渲染或逐页重读，但须在coverage如实说明。未核验的缺项先实际核验，不能直接抄齐清单。'
    body += '\n\n用户已授权加急案件独立验收使用gpt-6-astra/low，普通案件使用配置中的Sol/ultra（当前默认gpt-6.1-sol/ultra）；实际角色以context.review_route和真实CLI参数为准。加急只改变审查模型与排队槽，图表/Word/界面/视频的证据覆盖、哈希绑定和通过条件不变，返修使用显式repairer配置。旧规则中固定ultra的表述仅适用普通审查，不能要求加急案再排一次Sol Ultra，也不能自行切模型或自签通过。'
    builder = cfg.get('models', {}).get('builder', {}).get('model')
    if builder:
        repairer = model_for_stage(cfg, 'repair_final')
        body += '\n\n建设使用' + builder + '/high；返修（含录制问题准备/修复）使用' + repairer['model'] + '/' + repairer['reasoning_effort'] + '；普通独立验收使用配置中的Sol/ultra（当前默认gpt-6.1-sol/ultra）、明确加急gpt-6-astra/low。此显式路由覆盖旧规则中的返修high表述，实际CLI参数为准，禁止静默回退。'
    if context.get('pipeline_profile') == 'deliverable-first-v1':
        body += '\n\n' + (Path(__file__).resolve().parent.parent / 'rules' / 'deliverable-first.md').read_text(encoding='utf-8')
        body += '\n\n' + (Path(__file__).resolve().parent.parent / 'rules' / 'case-design.md').read_text(encoding='utf-8')
    body += '\n\n共享docs/rules/scripts路径相对于RUNNER_CONTEXT_JSON.project_root；只读共享规则，不在案件目录猜测同名文件。工具路径使用context.runtime，缺少桌面专用工具时使用本项目脚本和已配置运行库，不能凭空假定可调用插件。'
    return body + "\n\nRUNNER_CONTEXT_JSON:\n" + json.dumps(context, ensure_ascii=False, indent=2) + "\n"


def cli_terminal_completed(log: Path) -> bool:
    """Read only the real final protocol event, never tool-output text."""
    try:
        with log.open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 131072))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
        last = next((line for line in reversed(lines) if line.strip()), '')
        event = json.loads(last)
        return isinstance(event, dict) and event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict)
    except (OSError, ValueError):
        return False


def wait_for_cli_exit(proc, prompt_text: str, timeout: float, log: Path, *, terminal_grace: float = 60) -> bool:
    """Allow shutdown grace, then close only this completed CLI, never its tree."""
    deadline = time.monotonic() + timeout
    first = True
    terminal_since = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(proc.args, timeout)
        data = prompt_text if first else None
        first = False
        try:
            proc.communicate(data, timeout=min(10, remaining))
            return False
        except subprocess.TimeoutExpired:
            if not cli_terminal_completed(log):
                terminal_since = None
                continue
            now = time.monotonic()
            if terminal_since is None:
                terminal_since = now
            if now - terminal_since < terminal_grace:
                continue
            # Popen owns the process handle; PID reuse cannot redirect this action.
            proc.terminate()
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=10)
            return True


def worker_call_completed(record: dict) -> bool:
    if record.get('timed_out'):
        return False
    if record.get('exit_code', 0) == 0:
        return True
    return bool(record.get('terminal_cli_cleanup') and record.get('terminal_completed')
                and record.get('final_message'))


def invoke(cfg: dict, case: Path, stage: str, context: dict, output: Path | None = None) -> dict:
    command = command_for(cfg, case, stage, output)
    prompt_text = prompt(cfg, stage, context)
    logs = case / "logs"
    logs.mkdir(exist_ok=True)
    stamp = f"{int(time.time() * 1000)}-{stage}"
    log = logs / f"{stamp}.jsonl"
    start = time.time()
    model = model_for_stage(cfg, stage)
    log_stream = log.open("w", encoding="utf-8")
    error_stream = (logs / f"{stamp}.stderr.txt").open("w", encoding="utf-8")
    kwargs = {"stdin": subprocess.PIPE, "stdout": log_stream, "stderr": error_stream,
              "text": True, "encoding": "utf-8", "errors": "replace", "shell": False, "cwd": case}
    isolated_temp = case / ".runtime" / "tmp"
    isolated_temp.mkdir(parents=True, exist_ok=True)
    kwargs["env"] = {**os.environ, "TEMP": str(isolated_temp), "TMP": str(isolated_temp), "TMPDIR": str(isolated_temp)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        log_stream.close()
        error_stream.close()
        error = f"{type(exc).__name__}: {exc}"
        log.write_text("", encoding="utf-8")
        (logs / f"{stamp}.stderr.txt").write_text(error, encoding="utf-8")
        return {"stage": stage, "command": command, "model": model["model"],
                "reasoning_effort": model["reasoning_effort"],
                "sandbox": "read-only" if stage.startswith("review_") else "workspace-write",
                "thread_id": None, "exit_code": -1, "timed_out": False,
                "duration_seconds": round(time.time() - start, 2), "log": str(log), "error": error}
    timed_out = False
    terminal_cleanup = False
    kill_error = None
    try:
        timeout = cfg["runner"].get("review_timeout_seconds", 900) if stage.startswith("review_") else cfg["runner"].get("model_timeout_seconds", 7200)
        terminal_cleanup = wait_for_cli_exit(proc, prompt_text, timeout, log)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30, check=False)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError) as exc:
            kill_error = f"{type(exc).__name__}: {exc}"
        finally:
            if proc.poll() is None:
                proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
    log_stream.close()
    error_stream.close()
    stdout = log.read_text(encoding="utf-8", errors="replace")
    stderr = (logs / f"{stamp}.stderr.txt").read_text(encoding="utf-8", errors="replace")
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    thread_id = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
    final = next((e.get("item", {}).get("text") for e in reversed(events) if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"), None)
    usage_events = [e["usage"] for e in events if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict)]
    token_usage = {key: sum(u.get(key, 0) for u in usage_events if isinstance(u.get(key), (int, float)))
                   for key in {k for u in usage_events for k in u}}
    record = {"stage": stage, "command": command, "model": model["model"], "reasoning_effort": model["reasoning_effort"],
              "token_usage": token_usage or None,
              "sandbox": "read-only" if stage.startswith("review_") else "workspace-write",
              "thread_id": thread_id, "exit_code": proc.returncode, "timed_out": timed_out,
              "terminal_cli_cleanup": terminal_cleanup,
              "terminal_completed": cli_terminal_completed(log),
              "duration_seconds": round(time.time() - start, 2), "log": str(log), "final_message": final,
              "structured_output": str(output) if output and output.exists() else None,
              "error": (stderr[-4000:] if stderr else None) or kill_error}
    if output and output.exists():
        try:
            record["structured_result"] = read_json(output)
        except (OSError, ValueError):
            record["structured_result"] = None
    return record


def state_at(folder: Path, cid: str) -> Path:
    return folder / "state" / f"{cid}.json"


def policy_rejection_reported(reason: str) -> bool:
    """Require an affirmative rejection, retaining ambiguous mentions conservatively."""
    terms = re.compile(r'blocked by policy|policy rejection|策略拒绝|策略阻断', re.I)
    for clause in re.split(r'[。；;，,！!？?\n]|\.(?=\s|$)', str(reason)):
        for mention in terms.finditer(clause):
            before, after = clause[:mention.start()], clause[mention.end():]
            chinese_negative = re.search(
                r'(?:(?:尚未|未)(?:确认|确定|判定|证实|取得|获得)|'
                r'(?:尚不能|尚无法|不能|无法|不应|不可)(?:认定|归因|判定|确认|证明)|不推定)'
                r'[^。；;，,！!？?\n但]{0,48}$', before)
            english_negative = re.search(
                r'\b(?:not|no|without)\s+(?:(?:a|any|actual|confirmed|evidence\s+of)\s+)*$',
                before, re.I)
            negative_after = re.match(
                r'\s*(?:(?:尚未|未)(?:确认|证实)|'
                r'(?:(?:was|is|has been)\s+)?(?:not\s+(?:established|confirmed|proven)|unconfirmed|unproven)\b)',
                after, re.I)
            if not (chinese_negative or english_negative or negative_after):
                return True
    return False


def worker_blocker(case: Path, record: dict | None = None) -> dict | None:
    """Read current structured status, never infer a blocker from historical prose."""
    sources = (('.caseflow-environment.json', 'requires_environment_repair', 'Worker environment needs repair'),
               ('evidence/repair-status.json', 'requires_user_input', 'Repair requires external input'))
    for relative, flag, prefix in sources:
        path = case / relative
        note = read_json(artifact(case, relative)) if path.is_file() else {}
        from_final = False
        if relative == '.caseflow-environment.json' and record:
            for line in str(record.get('final_message') or '').splitlines():
                if line.startswith('CASEFLOW_ENVIRONMENT_BLOCKER:'):
                    note = json.loads(line.split(':', 1)[1].strip())
                    from_final = True
        if not isinstance(note, dict) or note.get('status') != 'blocked' or note.get(flag) is not True:
            continue
        reason = str(note.get('reason') or 'Required operation unavailable')
        policy = policy_rejection_reported(reason)
        category = 'tool_policy' if policy else 'worker_environment' if flag == 'requires_environment_repair' else 'external_input'
        return {'category': category, 'message': f'{prefix}: {reason}', 'source': relative,
                'source_sha256': sha256(path) if path.is_file() else None,
                'from_final_response': from_final,
                'fingerprint': hashlib.sha256((relative + '\n' + reason).encode('utf-8')).hexdigest()}
    return None


def deferred_worker_blocker(case: Path, state: dict) -> dict | None:
    blocker = worker_blocker(case)
    if blocker and (blocker['category'] in {'tool_policy', 'worker_environment'} or
                    os.environ.get('CASEFLOW_DEFER_EXTERNAL_BLOCKERS') == '1'):
        return blocker
    previous = state.get('worker_blocker') or {}
    if previous.get('from_final_response'):
        # A ready file predating the fallback cannot clear it. Require a new,
        # explicit ready result from the owner after the failed operation.
        path = case / previous['source']
        note = read_json(artifact(case, previous['source'])) if path.is_file() else {}
        if not (isinstance(note, dict) and note.get('status') == 'ready' and
                note.get('requires_environment_repair') is False and
                sha256(path) != previous.get('source_sha256')):
            return previous
    return None


def finish_delivery_cleanup(case: Path, folder: Path, state: dict):
    """A cleanup failure never changes a verified delivered case to blocked."""
    if state.get('cleanup_receipt') or state.get('cleanup_pending'):
        return  # No repeated attempts at a known external/ownership blocker.
    try:
        manifest = read_json(artifact(case, 'evidence/artifact-manifest.json'))
        report = read_json(artifact(case, manifest['capture_report'])) if manifest.get('capture_report') else {}
        from service_lifecycle import cleanup_after_delivery
        in_flight = any(state.get(key) for key in ('active_stage', 'waiting_stage', 'recording_pending'))
        control = read_json(folder / 'control.json') if (folder / 'control.json').is_file() else {}
        in_flight = bool(in_flight or control.get('keep_online'))
        receipt = cleanup_after_delivery(case, state['case_id'], report, in_flight=in_flight)
        # Receipt stays outside the accepted case tree so its hash does not
        # invalidate the final review or the already published delivery.
        path = folder / 'maintenance' / 'delivery-cleanup' / (state['case_id'] + '.json')
        atomic_json(path, receipt)
        state.update(cleanup_receipt=str(path), cleanup_pending=receipt['status'] != 'stopped')
    except Exception as exc:
        state.update(cleanup_pending=True, cleanup_error=f'{type(exc).__name__}: {exc}')


def run_case(cfg: dict, m: dict, folder: Path, entry: dict, *, executor=invoke) -> dict:
    cid = entry["case_id"]
    efficient = m.get('pipeline_profile') in {'efficient-v1', 'deliverable-first-v1'}
    owner = {'batch_id': m['batch_id'], 'case_id': cid, 'control': str(folder/'control.json')}
    def checkpoint():
        check_control(folder)
    safe_name = safe_case_name(entry["case_name"])
    duplicate = sum(safe_case_name(e["case_name"]).casefold() == safe_name.casefold() for e in m["cases"]) > 1
    delivery_name = entry.get("delivery_name", f"{safe_name}-{cid[:8]}" if duplicate else safe_name)
    if case_workspace(Path(m["output_root"]), {"case_id": cid, "workspace_name": delivery_name}).name != delivery_name:
        raise Blocked("Unsafe delivery name")
    expected_delivery = Path(m["output_root"]) / delivery_name
    state_file = state_at(folder, cid)
    state = read_json(state_file) if state_file.exists() else {"case_id": cid, "stage": "new", "calls": [], "repairs_visual": 0, "repairs_video": 0}
    state.pop('checkpoint_waiting', None)
    for key, value in (("calls", []), ("repairs_visual", 0), ("repairs_video", 0), ("repairs_final", 0)):
        state.setdefault(key, value)
    mode = cfg["runner"].get("review_mode", "split")
    if state.get("review_mode", mode) != mode:
        raise Blocked("Cannot change review mode for an existing case")
    state["review_mode"] = mode
    combined = mode == "combined_final"
    review_kinds = ("final",) if combined else ("visual", "video")
    def review_snapshot_fields():
        return {kind + "_snapshot": state[kind + "_review"]["snapshot_sha256"] for kind in review_kinds}
    def reviews_current():
        return all(state.get(kind + "_review", {}).get("verdict") == "pass" and
                   state[kind + "_review"].get("rules_version") == CHART_RULES_VERSION and
                   review_record_allowed(state[kind + "_review"], state) and
                   state[kind + "_review"].get("snapshot_sha256") == snapshot_id(snapshot(case, video=kind != "visual"))
                   for kind in review_kinds)
    if state['stage'] == 'blocked':
        blocked_case = case_workspace(folder, entry)
        blocker = deferred_worker_blocker(blocked_case, state)
        if blocker:
            state.update(worker_blocker=blocker, reason='Blocked: ' + blocker['message'],
                         resume_deferred='Current external blocker is unresolved; no model call dispatched')
            atomic_json(state_file, state)
            return state
        if state.get('worker_blocker'):
            state.setdefault('worker_blocker_history', []).append(state.pop('worker_blocker'))
        state.pop('resume_deferred', None)
    if state["stage"] == "blocked" and not entry["blocked_reason"]:
        state["stage"] = state.get("previous_stage", "new")
    if entry["blocked_reason"]:
        state.update(stage="blocked", reason=entry["blocked_reason"])
        atomic_json(state_file, state)
        return state
    case = case_workspace(folder, entry)
    state.update(case_name=entry["case_name"], workspace=str(case))
    parent = case.parent
    if not parent.exists():
        ancestor = parent.parent
        if has_path_link(ancestor):
            raise Blocked("Case workspace ancestor link refused")
        parent.mkdir(exist_ok=True)
    if has_path_link(parent):
        raise Blocked("Case workspace parent link refused")
    case.mkdir(exist_ok=True)
    if has_path_link(case):
        raise Blocked("Case workspace link refused")
    original = Path(entry["source_path"])
    if sha256(original) != entry["source_sha256"]:
        raise Blocked("Source changed since plan")
    source_dir = case / "source"
    source_dir.mkdir(exist_ok=True)
    if has_path_link(source_dir):
        raise Blocked("Source copy directory link refused")
    copy = source_dir / original.name
    if copy.exists():
        if copy.is_symlink():
            raise Blocked("Source copy link refused")
        if sha256(copy) != entry["source_sha256"]:
            raise Blocked("Copied source changed")
    else:
        shutil.copyfile(original, copy)
    if sha256(copy) != entry["source_sha256"] or sha256(original) != entry["source_sha256"]:
        raise Blocked("Source hash mismatch after copying")
    if state["stage"] == "delivered":
        delivered = Path(state["delivery"])
        if delivered != expected_delivery:
            raise Blocked("Recorded delivery path identity differs")
        expected = state.get("delivery_sha256") or {}
        actual = {p.relative_to(delivered).as_posix(): sha256(p) for p in delivered.rglob("*") if p.is_file()} if delivered.is_dir() and not delivered.is_symlink() else {}
        if not delivered.is_dir() or has_path_link(delivered) or not expected or actual != expected:
            raise Blocked("Recorded delivery is missing or changed")
        if not reviews_current():
            raise Blocked("Artifacts changed after recorded delivery")
        for kind in review_kinds:
            record = state.get(kind + "_review", {})
            report_path = inside(Path(record.get("path", "")), folder / "reviews" / cid, must_exist=True)
            if not record.get("report_sha256") or not report_path.is_file() or sha256(report_path) != record["report_sha256"]:
                raise Blocked("Recorded review report changed")
        if executor is invoke:
            finish_delivery_cleanup(case, folder, state)
            atomic_json(state_file, state)
        return state
    ctx = {"pipeline_profile": m.get('pipeline_profile','legacy'), "delivery_profile": m.get('delivery_profile','full'), "case_dir": str(case), "source_docx": str(copy), "case_name": entry["case_name"],
           "case_id": cid, "source_sha256": entry["source_sha256"], "batch_id": m["batch_id"],
           "source_relative_path": entry["relative_path"], "source_size": entry["source_size"],
           "input_directory": m["source_root"], "output_root": m["output_root"], "review_mode": mode,
           "case_resources": cfg.get("_case_resources", {}).get(cid, {}),
           "case_concurrency": cfg.get("execution", {}).get("case_concurrency", 1)}
    reviews = folder / "reviews" / cid
    reviews.mkdir(parents=True, exist_ok=True)
    if has_path_link(reviews):
        raise Blocked("Review directory link refused")
    def review_data(kind: str) -> dict | None:
        record = state.get(kind + "_review")
        if not record:
            return None
        path = inside(Path(record["path"]), reviews, must_exist=True)
        if sha256(path) != record.get("report_sha256"):
            raise Blocked("Review report changed")
        for name in ('raw', 'request'):
            if record.get(name + '_path'):
                proof = inside(Path(record[name + '_path']), reviews, must_exist=True)
                if sha256(proof) != record.get(name + '_sha256'):
                    raise Blocked('Review binding provenance changed')
        return read_json(path)
    def call(stage: str, extra: dict | None = None, output: Path | None = None):
        checkpoint()
        if stage == 'video' and efficient and executor is invoke:
            return scripted_video()
        while True:
            route = selected_review_route(folder, cid, cfg) if stage.startswith('review_') else None
            kind = route['slot'] if route else 'recording' if stage in {'video','repair_video'} else 'build'
            if efficient and stage == 'repair_video':
                kind = 'build'
            state['waiting_stage'] = stage
            if route:
                state['waiting_review_profile'] = route['profile']
            wait_started = time.time()
            atomic_json(state_file, state)
            def admission_checkpoint():
                checkpoint()
                if route and selected_review_route(folder,cid,cfg) != route:
                    raise ReviewRerouted()
            try:
                with stage_slot(cfg, kind, owner=owner, checkpoint=admission_checkpoint):
                    state.pop('waiting_stage', None)
                    state.pop('waiting_review_profile', None)
                    waits = state.setdefault('slot_wait_seconds', {})
                    waits[stage] = round(waits.get(stage, 0) + time.time() - wait_started, 3)
                    return call_now(stage, extra, output, route=route)
            except ReviewRerouted:
                continue
    def call_now(stage: str, extra: dict | None = None, output: Path | None = None, *, route=None):
        if stage.startswith("review_"):
            # Reserve durably before dispatch: failures and interrupted calls also consume this budget.
            used = state.setdefault("review_calls_started", max(state.get("astra_calls_started", 0), sum(c.get("stage", "").startswith("review_") for c in state["calls"])))
            limit = cfg["runner"].get("max_review_calls_per_case", cfg["runner"].get("max_astra_calls_per_case"))
            if limit is not None and used >= limit:
                raise Blocked(f"Reviewer call budget exhausted ({used}/{limit}); user decision required")
            state["review_calls_started"] = used + 1
            if route['authorization_id']:
                state.setdefault('review_authorizations', {})[route['authorization_id']] = dict(route)
            state['active_review_profile'] = route['profile']
        state.update(active_stage=stage, active_started_at=time.time())
        atomic_json(state_file, state)
        current = case / "evidence" / "artifact-manifest.json"
        current_data = None
        current_error = None
        if current.exists():
            try:
                current_data = read_json(artifact(case, "evidence/artifact-manifest.json"))
            except (Blocked, OSError, ValueError) as exc:
                current_error = str(exc)
        full = {**ctx, "stage": stage, "source_original": str(original), "batch_manifest": str(folder / "manifest.json"),
                "batch_review_dir": str(reviews), "artifact_manifest_path": str(current),
                "artifact_manifest": current_data, "artifact_manifest_error": current_error,
                "visual_review": review_data("visual"), "video_review": review_data("video"),
                "final_review": review_data("final"),
                **(extra or {})}
        if route:
            full['review_route'] = dict(route)
        if stage == 'video' and state.get('video_service_mismatch'):
            full['video_service_mismatch'] = state['video_service_mismatch']
            full['required_action'] = (
                '上次录制使用的服务身份与本案当前修复身份不一致。'
                '先只读核对本案 capture-plan.json、resources.json（若有）、健康接口返回的案件ID、工作区、端口、创建时间、PID、命令行和版本，'
                '再由 Sol high 让页面、录制计划、应用输入和当前健康身份指向同一个已核实服务；'
                '保全旧视频和日志，重新排练并录制，逐帧解码、抽帧核对交互与可见文案，重建 ui_text_audit、时间线及视频清单哈希。'
                '不得把旧服务的静态页面变化视为当前版本，也不得启动、重启、切换或用其他命令绕过被策略拒绝的服务。'
                '完成前不能送独立验收；详见 video_service_mismatch.evidence。'
            )
        track_inputs = stage == 'repair_final' or (efficient and stage in {'repair_video','repair_visual','prepare_video'})
        before_recording = None
        if track_inputs:
            try:
                before_recording = recording_inputs(case, pipeline_profile=m.get('pipeline_profile', 'legacy'))
            except (Blocked, OSError, ValueError) as exc:
                if m.get('pipeline_profile') != 'deliverable-first-v1':
                    raise
                # A broken preparation must reach its repairer. Never treat it
                # as an unchanged recording; validate the repaired inputs below.
                state['recording_pending'] = True
                full['recording_input_error'] = str(exc)
        before_video = current_video_hash(case) if stage == 'video' else None
        if stage == 'repair_final':
            full['recording_allowed'] = False
            full['required_action'] = str(full.get('required_action', '')) + ' 本阶段不占录制槽，禁止录屏；先完成材料/代码/图文/UI返修并自检。涉及画面变化时父执行器随后排队video阶段重录，只改Word正文不重录。'
        if efficient and stage in {'prepare_video','repair_video'}:
            full['recording_allowed'] = False
            full['required_action'] = str(full.get('required_action','')) + ' 本阶段只准备或修复实际页面与声明式capture-plan.json，不录屏、不停服务；父执行器在批次冻结的录制槽中运行可信录制程序。'
        rec = executor(review_call_config(cfg, route) if route else cfg, case, stage, full, output)
        if route:
            rec.update(review_profile=route['profile'], review_authorization_id=route['authorization_id'])
        state["calls"].append(rec)
        atomic_json(state_file, state)
        if not stage.startswith('review_'):
            blocker = worker_blocker(case, rec)
            if blocker:
                if stage == 'video' or track_inputs:
                    state['recording_pending'] = True
                state['worker_blocker'] = blocker
                atomic_json(state_file, state)
                raise WorkerBlocked(blocker)
        if not worker_call_completed(rec):
            raise Blocked(f"{stage} failed or timed out; see {rec.get('log', 'call record')}")
        if not rec.get("thread_id"):
            raise Blocked(f"{stage} did not provide a Codex thread ID")
        if route and (not review_record_allowed(rec,state) or any(rec.get(key)!=route[key] for key in ('model','reasoning_effort'))):
            raise Blocked('Review did not run on its explicitly selected route')
        if track_inputs:
            after_recording = recording_inputs(case, pipeline_profile=m.get('pipeline_profile', 'legacy'))
            state['recording_pending'] = bool(state.get('recording_pending') or (efficient and stage == 'repair_video') or after_recording != before_recording or
                any(str(i.get('artifact', '')).lower().endswith(('.mp4', '.webm')) or 'video' in str(i.get('artifact', '')).lower() or 'recording' in str(i.get('artifact', '')).lower()
                    for i in (full.get('review') or {}).get('issues', [])))
        if stage == 'video':
            after_video = current_video_hash(case)
            if state.get('recording_pending') and (not after_video or after_video == before_video):
                raise Blocked('Recording remains pending: video worker did not produce a new video artifact')
            state['recording_pending'] = False
        atomic_json(state_file, state)
        repair_status = case / "evidence" / "repair-status.json"
        if stage.startswith("repair_") and repair_status.is_file():
            note = read_json(artifact(case, "evidence/repair-status.json"))
            if note.get("status") in {"authorized_pending_repair", "pending_owner_repair"}:
                raise Blocked("Authorized material repair remains unfinished; preserve its evidence and continue this case")
        state.pop('active_stage', None)
        state.pop('active_started_at', None)
        state.pop('active_review_profile', None)
        atomic_json(state_file, state)
        return rec
    def scripted_video():
        from capture_runner import capture, validate_plan, CaptureError, CaptureEnvironmentError
        resources=cfg.get('_case_resources',{}).get(cid,{})
        while True:
            checkpoint()
            try:
                plan=validate_plan(case,cid,resources['ports'])
                if m.get('pipeline_profile') == 'deliverable-first-v1' and plan.get('schema_version') != 2:
                    raise CaptureError('Prepare both recording pages and bind scene data with capture schema 2')
                state['waiting_stage']='capture_video'
                atomic_json(state_file,state)
                queued=time.monotonic()
                with stage_slot(cfg,'recording',owner=owner,checkpoint=checkpoint):
                    state.pop('waiting_stage',None)
                    state.update(active_stage='capture_video',active_started_at=time.time())
                    atomic_json(state_file,state)
                    report=capture(cfg,case,cid,resources)
                    # A fresh trusted capture may encode identical stable pixels.
                    # Its new raw-recording provenance proves execution; changed bytes
                    # alone do not prove a repair, and the independent review still applies.
                    if not report.get('video_sha256') or report['video_sha256'] != current_video_hash(case):
                        raise CaptureError('Capture report does not bind the current video')
                state.pop('active_stage',None);state.pop('active_started_at',None)
                state.setdefault('script_calls',[]).append({'stage':'capture_video','execution':'trusted_script','model':None,
                    'slot_wait_seconds':round(time.monotonic()-queued-report['duration_seconds'],3),**report})
                state['recording_pending']=False
                atomic_json(state_file,state)
                return report
            except CaptureEnvironmentError as exc:
                state.pop('active_stage',None);state.pop('active_started_at',None);state.pop('waiting_stage',None)
                state['recording_pending']=True
                state.setdefault('capture_failures',[]).append({'time':time.time(),'error':str(exc),'environment':True})
                atomic_json(state_file,state)
                raise Blocked('Capture service identity requires owner verification; no paid repair dispatched: '+str(exc)) from exc
            except (CaptureError, subprocess.SubprocessError, KeyError) as exc:
                state.pop('active_stage',None);state.pop('active_started_at',None);state.pop('waiting_stage',None)
                state['recording_pending']=True
                state.setdefault('capture_failures',[]).append({'time':time.time(),'error':str(exc)})
                atomic_json(state_file,state)
                if any(term in str(exc).lower() for term in (
                        'blocked by policy', 'access is denied', 'eacces', 'eperm',
                        'memoryerror', 'memory allocation', 'out of memory')):
                    raise Blocked('Capture environment rejected the operation; no alternate execution attempted: '+str(exc)) from exc
                call('prepare_video',{'capture_error':str(exc),'required_action':'只修复本次明确的录制计划、当前服务或页面就绪问题，复用已完成成果。缺计划时按efficient-pipeline规则准备，实际probe并看图。禁止重建无关模块或改变审查模型。'})
    def accepted(kind: str, required: set[str], files: dict[str, str]) -> bool:
        old = state.get(kind + "_review", {})
        if old.get("verdict") != "pass" or old.get("rules_version") != CHART_RULES_VERSION or old.get("snapshot_sha256") != snapshot_id(files):
            return False
        if verify_review(review_data(kind), files, required, manifest=read_json(artifact(case, 'evidence/artifact-manifest.json')),
                         pipeline_profile=m.get('pipeline_profile', 'legacy')) != "pass":
            return False
        if not review_record_allowed(old, state):
            raise Blocked("Review route identity missing")
        return True
    def review(kind: str, required: set[str], files: dict[str, str]) -> str:
        output = reviews / f"{kind}-{time.time_ns()}.json"
        previous_files = state.get(kind + "_review", {}).get("snapshot_files", {})
        request = review_request(files, required)
        request_file = output.with_suffix('.request.json')
        atomic_json(request_file, {**request, 'snapshot_files': files, 'required_files': sorted(required)})
        rec = call("review_" + kind, {"snapshot_sha256": snapshot_id(files),
                                "review_request": request,
                                "review_request_path": str(request_file),
                                "snapshot_files": {p: files[p] for p in sorted(required)},
                                "changed_files": sorted(p for p in set(files) | set(previous_files) if files.get(p) != previous_files.get(p)) if previous_files else sorted(required),
                                "required_review_files": sorted(required), "review_output": str(output)}, output)
        result = read_json(output)
        manifest = read_json(artifact(case, 'evidence/artifact-manifest.json'))
        raw_output = None
        if isinstance(result, dict) and result.get('protocol') == 'evidence-ids-v1':
            if snapshot(case, video=kind != 'visual') != files:
                raise Blocked('Artifacts changed during review; refusing to bind stale evidence')
            result = bind_review_response(result, request, files, required, manifest, pipeline_profile=m.get('pipeline_profile', 'legacy'))
            raw_output = output
            output = output.with_suffix('.bound.json')
            atomic_json(output, result)
        verdict, integrity_warning = review_outcome(result, files, required, manifest=manifest, pipeline_profile=m.get('pipeline_profile', 'legacy'))
        if not review_record_allowed(rec, state):
            raise Blocked("Review did not run on required route")
        state[kind + "_review"] = {"path": str(output), "snapshot_sha256": snapshot_id(files), "snapshot_files": files, "verdict": verdict,
                                   "rules_version": CHART_RULES_VERSION,
                                   "model": rec["model"], "reasoning_effort": rec["reasoning_effort"],
                                   "sandbox": rec["sandbox"], "thread_id": rec.get("thread_id"), "report_sha256": sha256(output)}
        state[kind + '_review'].update(review_profile=rec['review_profile'], review_authorization_id=rec['review_authorization_id'])
        if raw_output:
            state[kind + '_review'].update(raw_path=str(raw_output), raw_sha256=sha256(raw_output), request_path=str(request_file), request_sha256=sha256(request_file))
        if integrity_warning:
            state[kind + "_review"].update(advisory_only=True, integrity_warning=integrity_warning,
                missing_evidence=sorted(required - {r['path'] for r in result['reviewed_files']}))
            if integrity_warning.startswith('Review contains stale/wrong hash: '):
                state[kind + "_review"]["advisory_only_hash_error"] = integrity_warning
        atomic_json(state_file, state)
        return verdict
    def controlled(mode: str):
        checkpoint()
        if executor is not invoke:
            return  # Isolated tests inject an executor; production has no bypass flag.
        a = read_json(artifact(case, "evidence/artifact-manifest.json"))
        paths = [a["revised_docx"], *[c["png"] for c in a["charts"]]] if mode == "word" else [a["video"]]
        fingerprint = snapshot_id({p: sha256(artifact(case, p)) for p in paths})
        previous = state.get("controlled_" + mode, {})
        if (previous.get("input_sha256") == fingerprint and previous.get("files") and
                all(a.get(k) == v for k, v in previous.get("manifest_fields", {}).items()) and
                all((case / p).is_file() and sha256(artifact(case, p)) == h for p, h in previous["files"].items())):
            return
        cmd = [cfg["runtime"]["python"], "-X", "utf8", str(cfg["_base"] / "scripts/controlled_evidence.py"), mode,
               str(case), str(copy), "--config", str(cfg["_config_path"])]
        with stage_slot(cfg, "evidence", owner=owner, checkpoint=checkpoint):
            completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        (case / "logs").mkdir(exist_ok=True)
        (case / "logs" / f"controlled-{mode}-{time.time_ns()}.log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise Blocked(f"Controlled {mode} evidence failed: {completed.stderr[-3000:]}")
        result = json.loads(completed.stdout)
        state["controlled_" + mode] = {"input_sha256": fingerprint, **result}
        atomic_json(state_file, state)
    def checked(video: bool):
        kind = "video" if video else "visual"
        while True:
            try:
                # Find cheap metadata errors before rendering/recording. The same
                # validator is available to the builder inside its initial call.
                validate_build_contract(case, entry['source_sha256'])
                if video and efficient and state.get('recording_pending'):
                    call('video')
                controlled("word")
                if video:
                    controlled("video")
                return validate_manifest(case, entry["source_sha256"], video=video, cfg=cfg)
            except (Blocked, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                # Environment failures cannot be fixed by paying for another
                # model call. Preserve the exact classification and stop this
                # case so the owner can repair the runtime or policy boundary.
                from runtime_doctor import failure_kind
                environment_kind = failure_kind(f"{type(exc).__name__}: {exc}")
                if environment_kind in {'policy_denied', 'memory_exhausted', 'permission_or_lock'}:
                    blocker = {'category': environment_kind, 'message': str(exc),
                               'stage': 'controlled_' + kind}
                    state['worker_blocker'] = blocker
                    state['resume_deferred'] = 'Environment blocker retained; no paid retry dispatched'
                    atomic_json(state_file, state)
                    raise Blocked(f"{environment_kind}: {exc}") from exc
                if max_repairs is not None and state["repairs_" + kind] >= max_repairs:
                    raise Blocked(f"{kind} mechanical validation exhausted repairs: {exc}") from exc
                state["repairs_" + kind] += 1
                atomic_json(state_file, state)
                call("repair_" + kind, {"mechanical_validation_error": str(exc), "required_action": "修复实际合同错误；缺失或残缺视频须重新录制并补齐清单，不能只保留video路径。"})
    def run_split_reviews():
        while True:
            _, required = checked(False)
            files = snapshot(case, video=False)
            if accepted("visual", required, files):
                break
            verdict = review("visual", required, files)
            if verdict == "pass":
                break
            if verdict == "blocked" or (max_repairs is not None and state["repairs_visual"] >= max_repairs):
                raise Blocked("Visual review rejected")
            state["repairs_visual"] += 1
            call("repair_visual", {"review": review_data("visual")})
        state["stage"] = "visual_pass"
        atomic_json(state_file, state)
        if state.get("video_review", {}).get("verdict") != "pass":
            if not (case / "evidence" / "artifact-manifest.json").exists():
                raise Blocked("Missing artifact manifest")
            current = read_json(case / "evidence" / "artifact-manifest.json")
            if not current.get("video"):
                call("video")
        while True:
            a, required = checked(True)
            visual_files = snapshot(case, video=False)
            if not accepted("visual", validate_manifest(case, entry["source_sha256"], video=False, cfg=cfg)[1], visual_files):
                verdict = review("visual", validate_manifest(case, entry["source_sha256"], video=False, cfg=cfg)[1], visual_files)
                if verdict != "pass":
                    if verdict == "blocked" or (max_repairs is not None and state["repairs_visual"] >= max_repairs):
                        raise Blocked("Visual changed and re-review rejected")
                    state["repairs_visual"] += 1
                    call("repair_visual", {"review": review_data("visual")})
                    call("video")
                    continue
            files = snapshot(case, video=True)
            if accepted("video", required, files):
                break
            verdict = review("video", required, files)
            if verdict == "pass":
                break
            if verdict == "blocked" or (max_repairs is not None and state["repairs_video"] >= max_repairs):
                raise Blocked("Video review rejected")
            state["repairs_video"] += 1
            call("repair_video", {"review": review_data("video")})

    if state["stage"] == "new":
        call("build")
        state["stage"] = "built"
        atomic_json(state_file, state)
    if state.get("needs_workspace_repair"):
        if state.get("workspace_copy") and (state.get("final_review") or {}).get("verdict") == "revise":
            service_policy = state.get("service_start_policy")
            required_action = (
                "本案必要写入拒绝已由保全式复制修复，但本案服务启动命令被执行策略在运行前拒绝，详见service_start_policy.evidence。"
                "本轮绝不启动任何服务，不换命令形式、端口、进程、父任务或权限路径重试。"
                "先按最近一次Ultra审查逐项修正算法和输入锚点，离线实际重算、有效性回归，更新CSV、PNG、来源追踪、README和结合上下文的红字Word；保留原件及历史。"
                "记录最终代码哈希、准确运行时、工作区、已分配端口及将来仅需一次的精确启动命令。"
                "因真实API、浏览器、重启读回和新视频仍需服务，repair-status.json须明确status=blocked、requires_user_input=true、具体策略阻断与未验证范围；"
                "保留recording_pending，不得声称业务闭环或视觉验收通过。本阶段不录屏。"
                if service_policy else
                "本案因必要写入拒绝已保全式复制，旧树在workspace_copy.backup；复用已修代码、计算、Word和图表，继续落实最近一次独立验收的具体返修意见。"
                "先预检当前工作区写入及本案服务身份，使用当前代码和真实API完成尚缺业务链、重启读回、浏览器、导出与证据更新，保留原件和历史记录。"
                "本阶段不录屏；画面受影响由父执行器随后排队video重录，不可用旧视频或旧截图冒充完成。"
            )
            call("repair_final", {"workspace_migration": state["workspace_migration"],
                  "review": review_data("final"),
                  "service_start_policy": service_policy,
                  "required_action": required_action})
        else:
            call("repair_visual", {"workspace_migration": state["workspace_migration"],
                  "required_action": "复用已有系统、Word及图表，修复迁移后的绝对路径和启动命令，应用最新web可见文案规则；数据来源和未验证范围集中写入README.md。重新检查全部路由和交互并更新截图与ui_text_audit。保留源文件和已有计算，不从零重建；本轮不录制，随后独立video阶段重录。"})
        state.pop("needs_workspace_repair", None)
        atomic_json(state_file, state)
    max_repairs = cfg["runner"].get("max_repairs_per_review", 2)
    if combined:
        pending_repair = case / "evidence" / "repair-status.json"
        if pending_repair.is_file():
            pending = read_json(artifact(case, "evidence/repair-status.json"))
            if pending.get('status') == 'pending_owner_repair':
                instruction = pending.get('required_action')
                if not isinstance(instruction, str) or not instruction.strip():
                    raise Blocked('Owner repair requires a concrete instruction')
                state['repairs_final'] += 1
                atomic_json(state_file, state)
                call('repair_final', {'review': review_data('final'), 'owner_repair': pending,
                                     'required_action': instruction})
            elif pending.get("status") == "authorized_pending_repair" and pending.get("user_authorized_autofill") is True:
                # Explicit new authorization reopens only this unfinished case; old reviews stay hash-bound.
                state["repairs_final"] += 1
                atomic_json(state_file, state)
                call("repair_final", {"review": review_data("final"), "authorized_material_autofill": pending,
                                      "required_action": "按最新material-sourcing规则复用已有成果，检索适配公开资源，剩余输入以明确假设和可复现脚本补齐并实际运行；更新图、Web、Word、证据和README，自检完成后将repair-status置ready_for_review。不得再因旧专用数据或现场设备缺口暂停。"})
            elif pending.get("status") == "blocked" and pending.get("requires_user_input") is True:
                # A resumed worker must resolve its external blocker before another paid review.
                state["repairs_final"] += 1
                atomic_json(state_file, state)
                service_policy = state.get("service_start_policy")
                call("repair_final", {"review": review_data("final"), "external_blocker": pending,
                                      "service_start_policy": service_policy,
                                      "required_action": (
                                          "外部条件已由负责人解除时，先只读核对本案 capture-plan.json、resources.json（若有）、"
                                          "健康接口及服务启动证据中的案件ID、工作区、端口、PID、创建时间、命令行和版本是否完全一致；"
                                          "复用已核实的现有服务，严禁停止、重启、切换进程或用其他命令绕过策略拒绝。"
                                          "按本案自己的 API、数据输入和脚本完成真实计算、读回、浏览器交互与导出检查，"
                                          "仅保留本案相关的已有成果；本阶段不录屏，页面或输入变化由父执行器随后排队 video。"
                                          "若服务仍未监听、身份不符或缺少合法解除证据，保持 repair-status=blocked、recording_pending=true，"
                                          "保全离线成果和旧阻塞记录，禁止重复被拒绝启动。"
                                      )})
        checked(False)
        current = read_json(case / "evidence" / "artifact-manifest.json")
        if not current.get("video") or state.get('recording_pending'):
            call("video")
        while True:
            if state.get('recording_pending'):
                call('video')
            _, required = checked(True)
            files = snapshot(case, video=True)
            if accepted("final", required, files):
                break
            prior = state.get("final_review", {})
            repair_limit = cfg["runner"].get("max_final_review_repairs", 1)
            if prior.get("verdict") in {"revise", "blocked"} and prior.get("snapshot_sha256") == snapshot_id(files):
                if repair_limit is not None and state["repairs_final"] >= repair_limit:
                    raise Blocked("Final review rejected after permitted repair; user decision required")
                call_limit = cfg["runner"].get("max_review_calls_per_case", cfg["runner"].get("max_astra_calls_per_case"))
                if call_limit is not None and state.get("review_calls_started", state.get("astra_calls_started", 0)) >= call_limit:
                    raise Blocked("Reviewer call budget exhausted; user decision required")
                # Keep cumulative accounting across restarts, even when the user permits continued repair.
                state["repairs_final"] += 1
                atomic_json(state_file, state)
                call("repair_final", {"review": review_data("final"),
                                      "required_action": (
                                          "一次修复全部有依据的问题并自检。Word及文档专用图只更新相关图文、清单和渲染；仅录制页面或其实际输入变化才刷新截图、计划并由父执行器重录。保留完整网页框架，其余空模块无需补齐。本阶段不录屏。"
                                          if m.get('pipeline_profile') == 'deliverable-first-v1' else
                                          "一次修复全部有依据的问题并自检；改动网页或图表时同步Word与截图，父执行器随后重录受影响视频。本返修阶段不录屏。")})
                continue
            verdict = review("final", required, files)
            if verdict == "pass":
                break
            if repair_limit is not None and state["repairs_final"] >= repair_limit:
                raise Blocked("Final review rejected; user decision required")
        state["stage"] = "final_pass"
        atomic_json(state_file, state)
    else:
        run_split_reviews()
    # Final source/artifact hashes are checked again before an atomic delivery rename.
    if sha256(original) != entry["source_sha256"] or sha256(copy) != entry["source_sha256"]:
        raise Blocked("Source changed before delivery")
    a, _ = validate_manifest(case, entry["source_sha256"], video=True, cfg=cfg)
    if not reviews_current():
        raise Blocked("Artifacts changed after review")
    checkpoint()
    with cfg.get("_publication_lock", threading.RLock()):
        output_root = Path(m["output_root"])
        if has_path_link(output_root):
            raise Blocked("Output root link refused")
        if output_root.exists() and not output_root.is_dir():
            raise Blocked("Output root is not a directory")
        if output_root.exists() and any(output_root.iterdir()) and not (folder / "output-owner.json").exists():
            raise Blocked("Existing nonempty output root is not owned by batch")
        output_root.mkdir(parents=True, exist_ok=True)
        owner = folder / "output-owner.json"
        if owner.exists() and read_json(owner).get("batch_id") != m["batch_id"]:
            raise Blocked("Output ownership mismatch")
        if not owner.exists():
            atomic_json(owner, {"batch_id": m["batch_id"], "output_root": str(output_root)})
        dest = expected_delivery
        intent = folder / "publish-intents" / f"{cid}.json"
        if dest.exists():
            if not intent.is_file() or intent.is_symlink():
                raise Blocked("Existing delivery cannot be overwritten")
            receipt = read_json(intent)
            expected = receipt.get("delivery_sha256", {})
            actual = {p.relative_to(dest).as_posix(): sha256(p) for p in dest.rglob("*") if p.is_file()} if dest.is_dir() and not dest.is_symlink() else {}
            if (receipt.get("batch_id") != m["batch_id"] or receipt.get("case_id") != cid or
                    receipt.get("source_sha256") != entry["source_sha256"] or
                    any(receipt.get(k) != v for k, v in review_snapshot_fields().items()) or
                    not expected or actual != expected):
                raise Blocked("Existing delivery identity differs")
            state.update(stage="delivered", delivery=str(dest), delivery_sha256=expected, reason=None)
            atomic_json(state_file, state)
            if executor is invoke:
                finish_delivery_cleanup(case, folder, state)
                atomic_json(state_file, state)
            return state
        staging = output_root / f".{cid}.staging-{os.getpid()}"
        if staging.exists():
            raise Blocked("Existing staging directory")
        staging.mkdir()
        try:
            expected_files = {}
            def staged_copy(src: Path, dst: Path) -> None:
                shutil.copyfile(src, dst)
                digest = sha256(src)
                if sha256(dst) != digest:
                    raise Blocked(f"Staging hash mismatch: {dst.name}")
                expected_files[dst.relative_to(staging).as_posix()] = digest
            staged_copy(artifact(case, a["revised_docx"]), staging / original.name)
            compact_delivery = m.get('delivery_profile', 'full') == 'word-video'
            if not compact_delivery and a.get("readme"):
                staged_copy(artifact(case, a["readme"]), staging / "README.md")
            if not compact_delivery:
                (staging / "原始文件").mkdir()
                staged_copy(copy, staging / "原始文件" / original.name)
            (staging / "模拟系统").mkdir()
            staged_copy(artifact(case, a["video"]), staging / "模拟系统" / f"{safe_name}.mp4")
            chart_dir = staging / "图表资料"
            if not compact_delivery:
                chart_dir.mkdir()
            used = set()
            for item in ([] if compact_delivery else a.get("charts", [])):
                for field in ("csv", "png", "explanation"):
                    if not item.get(field):
                        continue
                    p = artifact(case, item[field])
                    if p.name.casefold() in used:
                        raise Blocked("Chart filenames collide")
                    used.add(p.name.casefold())
                    staged_copy(p, chart_dir / p.name)
            if not compact_delivery and expected_files[f"原始文件/{original.name}"] != entry["source_sha256"]:
                raise Blocked("Staging hash mismatch")
            if not reviews_current():
                raise Blocked("Artifacts changed during staging")
            if dest.exists():
                raise Blocked("Delivery appeared during staging")
            atomic_json(intent, {"batch_id": m["batch_id"], "case_id": cid,
                                 "source_sha256": entry["source_sha256"],
                                 **review_snapshot_fields(),
                                 "delivery_sha256": expected_files})
            staging.rename(dest)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        state.update(stage="delivered", delivery=str(dest), delivery_sha256={p.relative_to(dest).as_posix(): sha256(p) for p in dest.rglob("*") if p.is_file()}, reason=None)
        atomic_json(state_file, state)
        if executor is invoke:
            finish_delivery_cleanup(case, folder, state)
            atomic_json(state_file, state)
        return state


def run_batch(cfg: dict, ref: str, *, dry_run: bool = False, executor=invoke, case_ids=None) -> dict:
    m, folder = load_batch(cfg, ref)
    # Keep scheduler capacity immutable for this batch.  This makes changing
    # the machine-wide defaults safe: only newly planned batches receive the
    # faster recording profile.
    cfg = apply_frozen_execution_profile(cfg, m)
    selected_entries = m['cases']
    scope = {}
    if case_ids is not None:
        known = {e['case_id'] for e in m['cases']}
        if not case_ids or len(case_ids) != len(set(case_ids)) or set(case_ids) - known:
            raise Blocked('Selected case IDs must be nonempty, unique and part of this batch')
        selected_entries = [e for e in m['cases'] if e['case_id'] in case_ids]
        scope = {'scope':'selected_cases', 'selected_case_ids':list(case_ids), 'unselected_case_count':len(m['cases'])-len(selected_entries)}
    if dry_run:
        result = []
        stages = ("build", "repair_visual", "video", "repair_video", "review_final", "repair_final") if cfg["runner"].get("review_mode") == "combined_final" else ("build", "review_visual", "repair_visual", "video", "review_video", "repair_video")
        for e in selected_entries:
            case = case_workspace(folder, e)
            route_cfg = review_call_config(cfg, selected_review_route(folder, e['case_id'], cfg))
            commands = {s: command_for(route_cfg, case, s, folder / "reviews" / e["case_id"] / f"{s}.json", dry_run=True) for s in stages}
            if m.get('pipeline_profile') in {'efficient-v1', 'deliverable-first-v1'}:
                commands.pop('video', None)
                commands['prepare_video'] = command_for(cfg, case, 'prepare_video', dry_run=True)
                commands['capture_video'] = {'execution': 'parent_trusted_script', 'module': 'scripts/capture_runner.py', 'model': None, 'slot': 'recording'}
            result.append({"case_id": e["case_id"], "case_name": e["case_name"], "workspace": str(case), "blocked_reason": e["blocked_reason"],
                           "commands": commands})
        return {"batch_id": m["batch_id"], "dry_run": True, "execution": cfg.get("execution", {}), "cases": result, **scope}
    with BatchLock(folder):
        journal = folder / "workspace-migration.json"
        if journal.exists() and read_json(journal).get("status") != "complete":
            raise Blocked("Workspace migration incomplete; resume migrate before run")
        prepare_control_directories(cfg["_root"])
        selected_needs_execution = True
        if selected_entries:
            selected_needs_execution = False
            for entry in selected_entries:
                state_path = state_at(folder, entry['case_id'])
                try:
                    current = read_json(state_path) if state_path.is_file() else {}
                except (OSError, ValueError, TypeError):
                    current = {}
                if current.get('stage') != 'delivered' or current.get('recording_pending'):
                    selected_needs_execution = True
                    break
        if executor is invoke and selected_needs_execution:
            native_codex(cfg)
            for name in ("python", "ffmpeg", "ffprobe", "soffice", "pdftoppm", "docx_renderer"):
                value = cfg.get("runtime", {}).get(name)
                if not value or not Path(value).is_file():
                    raise Blocked(f"Missing runtime {name}; refresh config.json before building cases")
            if m.get('pipeline_profile') in {'efficient-v1', 'deliverable-first-v1'}:
                if not Path(cfg.get('runtime',{}).get('node','')).is_file() or not (Path(cfg.get('runtime',{}).get('node_modules',''))/'playwright/package.json').is_file():
                    raise Blocked('Trusted recorder requires configured Node and bundled Playwright')
            if cfg['runner'].get('environment_preflight', False):
                from runtime_doctor import check_environment
                preflight = check_environment(cfg, smoke=False)
                atomic_json(folder / 'environment-preflight.json', preflight)
                if not preflight['ok']:
                    raise Blocked('Environment preflight failed before model dispatch: ' + '; '.join(preflight['errors']))
        output = Path(m["output_root"])
        owner = folder / "output-owner.json"
        if has_path_link(output) or (output.exists() and not output.is_dir()):
            raise Blocked("Output root is not a plain directory")
        if output.exists() and any(output.iterdir()) and not owner.exists():
            raise Blocked("Existing nonempty output root is not owned by batch")
        control = cfg["_root"] / ".runtime" / "planning"
        control.mkdir(parents=True, exist_ok=True)
        with BatchLock(control):
            if assign_workspaces(m, folder, cfg["_root"]):
                atomic_json(folder / "manifest.json", m)
        paths = [str(case_workspace(folder, e)).casefold() for e in m["cases"]]
        if len(paths) != len(set(paths)):
            raise Blocked("Case workspaces collide")
        # A scoped recovery must not allocate ports or rewrite resources for
        # unselected cases. Existing rows remain intact for a later full run.
        cfg["_case_resources"] = allocate_resources(cfg, m, folder, entries=selected_entries)
        cfg["_publication_lock"] = threading.RLock()
        index = "# 案件工作区\n\n" + "\n".join(
            f"- [{workspace_title(e['case_name'])}](<{case_workspace(folder, e).as_posix()}>)" for e in m["cases"]) + "\n"
        (folder / "工作区索引.md").write_text(index, encoding="utf-8")
        def work(e):
            try:
                return run_case(cfg, m, folder, e, executor=executor)
            except Drained as exc:
                p=state_at(folder,e['case_id'])
                state=read_json(p) if p.exists() else {'case_id':e['case_id'],'stage':'new','calls':[]}
                state['checkpoint_waiting']=str(exc)
                state.pop('waiting_stage',None)
                atomic_json(p,state)
                return state
            except Exception as exc:
                p = state_at(folder, e["case_id"])
                state = read_json(p) if p.exists() else {"case_id": e["case_id"], "calls": []}
                checkpoint = state.get("previous_stage", "new") if state.get("stage") == "blocked" else state.get("stage", "new")
                state["failed_stage"] = state.pop("active_stage", None) or state.pop("waiting_stage", None)
                state.pop("waiting_stage", None)
                state.pop("active_started_at", None)
                state.pop('active_review_profile', None)
                state.update(previous_stage=checkpoint, stage="blocked", reason=f"{type(exc).__name__}: {exc}")
                state.update(case_name=e["case_name"], workspace=str(case_workspace(folder, e)))
                atomic_json(p, state)
                return state
        # Waiting on review/recording must not consume a construction permit.
        workers = min(32, len(selected_entries))
        build_limit = cfg.get('execution', {}).get('case_concurrency', 1)
        def current_states():
            return [compact_case_state(read_json(p), p) if p.exists() else {"case_id": e["case_id"], "case_name": e["case_name"],
                     "workspace": str(case_workspace(folder, e)), "stage": "queued"}
                    for e in selected_entries for p in [state_at(folder, e["case_id"])]]
        atomic_json(folder / "status.json", {"batch_id": m["batch_id"], "status": "running", "case_concurrency": build_limit, "pipeline_workers": workers, "cases": current_states(), **scope})
        results = {}
        ack_file=folder/'control-acks.json'
        acknowledgements=read_json(ack_file) if ack_file.is_file() else {}
        entries={e['case_id']:e for e in selected_entries}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="case") as pool:
            futures = {pool.submit(work, e): e["case_id"] for e in selected_entries}
            last_status = time.monotonic()
            while True:
                done,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED) if futures else (set(),set())
                for future in done:
                    results[futures.pop(future)]=future.result()
                control=read_json(folder/'control.json') if (folder/'control.json').is_file() else {}
                for cid, request in control.get('resume_requests',{}).items():
                    if cid not in entries or acknowledgements.get(cid,{}).get('request_id')==request['request_id']:
                        continue
                    if control.get('drain'):
                        continue
                    if cid in futures.values():
                        outcome='already_running'
                    elif results.get(cid,{}).get('stage')=='delivered':
                        outcome='already_delivered'
                    else:
                        futures[pool.submit(work,entries[cid])]=cid
                        outcome='resumed'
                    acknowledgements[cid]={'request_id':request['request_id'],'outcome':outcome,'time':time.time()}
                    atomic_json(ack_file,acknowledgements)
                if done or time.monotonic() - last_status >= 30:
                    atomic_json(folder / "status.json", {"batch_id": m["batch_id"], "status": "running", "case_concurrency": build_limit, "pipeline_workers": workers, "cases": current_states(), **scope})
                    last_status = time.monotonic()
                if not futures:
                    break
        statuses = [results[e["case_id"]] for e in selected_entries]
        summary = {"batch_id": m["batch_id"], "status": "complete" if all(s.get("stage") == "delivered" for s in statuses) else 'drained' if control.get('drain') else "needs_attention", "cases": statuses, **scope}
        atomic_json(folder / "status.json", {**summary, "cases": [compact_case_state(s, state_at(folder, s["case_id"])) for s in statuses]})
        return summary


def diagnose_batch(cfg, ref):
    """Compact, read-only diagnosis of exactly one registered batch, with no model calls."""
    manifest, folder = load_batch(cfg, ref)
    rows, counts, stages = [], {}, {}
    for entry in manifest['cases']:
        path = state_at(folder, entry['case_id'])
        state = read_json(path) if path.is_file() else {}
        stage = state.get('stage', 'planned')
        counts[stage] = counts.get(stage, 0) + 1
        calls = state.get('calls', [])
        for call in calls:
            metric = stages.setdefault(call['stage'], {'calls': 0, 'model_seconds': 0, 'failed_calls': 0})
            metric['calls'] += 1
            metric['model_seconds'] = round(metric['model_seconds'] + call.get('duration_seconds', 0), 3)
            metric['failed_calls'] += int(not worker_call_completed(call))
            metric['terminal_cli_cleanups'] = metric.get('terminal_cli_cleanups', 0) + int(bool(call.get('terminal_cli_cleanup')))
        workspace = case_workspace(folder, entry)
        # Delivery validation remains the normal run contract. A diagnosis does
        # not revisit or certify completed work and does not scan other batches.
        blocker = worker_blocker(workspace) if stage != 'delivered' else None
        last = calls[-1] if calls else {}
        rows.append({'case_id': entry['case_id'], 'case_name': entry['case_name'], 'stage': stage,
                     'workspace': str(workspace), 'state_updated_at': path.stat().st_mtime if path.is_file() else None,
                     'active_stage': state.get('active_stage'), 'waiting_stage': state.get('waiting_stage'),
                     'failed_stage': state.get('failed_stage'), 'reason': state.get('reason'),
                     'current_blocker': blocker, 'calls': len(calls),
                     'slot_wait_seconds': state.get('slot_wait_seconds', {}),
                     'recording_pending': bool(state.get('recording_pending')),
                     'last_call': {key: last.get(key) for key in ('stage', 'log', 'model', 'reasoning_effort', 'sandbox', 'exit_code', 'timed_out')},
                     'last_worker_message': str(last.get('final_message') or '')[-1200:]})
    control_path = folder / 'control.json'
    return {'batch_id': manifest['batch_id'], 'read_only': True,
            'pipeline_profile': manifest.get('pipeline_profile', 'legacy'),
            'counts': counts, 'calls': sum(row['calls'] for row in rows), 'stage_costs': stages,
            'control': read_json(control_path) if control_path.is_file() else {}, 'cases': rows,
            'note': 'Model and queue durations overlap across cases; do not sum as batch elapsed time. '
                    'A worker exit code, preflight or diagnosis is not delivery or policy clearance. '
                    'Active state requires live process identity verification.'}


def control_batch(cfg, ref, action, *, case_id=None, value=None):
    import uuid
    m,folder=load_batch(cfg,ref)
    known={entry['case_id'] for entry in m['cases']}
    if case_id is not None and case_id not in known:
        raise Blocked('Unknown case for this batch')
    guard=folder/'control-edit';guard.mkdir(exist_ok=True)
    with BatchLock(guard):
        path=folder/'control.json'
        control=read_json(path) if path.is_file() else {}
        if action in ('drain','continue'):
            control['drain']=action=='drain'
        elif action=='resume-case':
            if not case_id:
                raise Blocked('resume-case requires the exact case ID')
            control.setdefault('resume_requests',{})[case_id]={'request_id':uuid.uuid4().hex,'time':time.time()}
        elif action=='priority':
            if type(value) is not int or not -100<=value<=100:
                raise Blocked('Priority must be an integer from -100 to 100')
            if case_id:
                control.setdefault('case_priorities',{})[case_id]=value
            else:
                control['priority']=value
        elif action=='expedite':
            selection={'profile':'expedited','authorization_id':uuid.uuid4().hex,'requested_at':time.time(),
                       'source':'Explicit user request for expedited Astra low review'}
            if case_id:
                control.setdefault('review_routes',{})[case_id]=selection
                control.setdefault('case_priorities',{})[case_id]=10
            else:
                control['review_route']=selection
                control['priority']=10
        else:
            raise Blocked('Unknown control action')
        atomic_json(path,control)
    active=False
    try:
        with BatchLock(folder):
            pass
    except Busy:
        active=True
    return {'batch_id':m['batch_id'],'action':action,'control':control,'executor_lock_held':active,
            'note':'New executor reads requests at safe stage boundaries. Existing older executors do not hot-load this feature. If no executor is active, run this confirmed batch to continue.'}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / "config.json")
    sub = parser.add_subparsers(dest="verb", required=True)
    for verb in ("plan", "status", "diagnose", "run", "migrate"):
        p = sub.add_parser(verb)
        p.add_argument("source_or_batch")
        if verb == "run":
            p.add_argument("--dry-run", action="store_true")
            p.add_argument('--case-id', action='append', dest='case_ids')
    p=sub.add_parser('control')
    p.add_argument('source_or_batch')
    p.add_argument('action',choices=['drain','continue','resume-case','priority','expedite'])
    p.add_argument('--case-id')
    p.add_argument('--value',type=int)
    doctor_parser = sub.add_parser('doctor', help='Check this computer without starting cases or model calls')
    doctor_parser.add_argument('--smoke', action='store_true', help='Also open an isolated browser and render a temporary sample Word')
    args = parser.parse_args(argv)
    try:
        cfg = config_at(args.config)
        if args.verb == 'doctor':
            from runtime_doctor import check_environment
            result = check_environment(cfg, smoke=args.smoke)
        elif args.verb == "plan":
            result = plan(cfg, Path(args.source_or_batch))
        elif args.verb == "migrate":
            result = migrate_batch(cfg, args.source_or_batch)
        elif args.verb == 'control':
            result=control_batch(cfg,args.source_or_batch,args.action,case_id=args.case_id,value=args.value)
        elif args.verb == 'diagnose':
            result = diagnose_batch(cfg, args.source_or_batch)
        elif args.verb == "status":
            m, folder = load_batch(cfg, args.source_or_batch)
            result = {"batch_id": m["batch_id"], "batch_workspace": str(folder), "cases": [read_json(p) if p.exists() else {"case_id": e["case_id"], "case_name": e["case_name"], "workspace": str(case_workspace(folder, e)), "stage": "planned", "blocked_reason": e["blocked_reason"]} for e in m["cases"] for p in [state_at(folder, e["case_id"])]]}
        else:
            result = run_batch(cfg, args.source_or_batch, dry_run=args.dry_run, case_ids=args.case_ids)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.verb == 'doctor':
            return 0 if result['ok'] else 2
        return 3 if args.verb == "run" and not args.dry_run and result.get("status") != "complete" else 0
    except (Blocked, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
