"""Project root, run discovery, run id allocation (SPEC §3, §7.2)."""

from __future__ import annotations

import fcntl
import os
import re
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from datetime import datetime
from pathlib import Path

from runops.config import ProjectConfig, find_project_root, load_config
from runops.errors import UsageError
from runops.manifest import MANIFEST_FILE, Manifest
from runops.util import dump_toml, load_toml, tomllib

RUN_ID_RE = re.compile(r"^R(\d{8})-(\d{4,})$")
STATE_DIR = ".runops"
INDEX_FILE = "index.toml"
ARCHIVE_DIR = "_archive"
SCRATCH_DIR = "_scratch"

_HELD = threading.local()  # per thread: lock path -> re-entry depth


class Project:
    """An opened runops project."""

    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.root = config.root

    @classmethod
    def open(cls, start: Path | None = None) -> Project:
        root = find_project_root(start)
        return cls(load_config(root))

    # ---- paths -------------------------------------------------------
    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def cases_dir(self) -> Path:
        return self.root / "cases"

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR

    @property
    def build_dir(self) -> Path:
        return self.state_dir / "build"

    @property
    def venv_dir(self) -> Path:
        return self.root / ".venv"

    def rel(self, path: Path) -> str:
        """Project-relative POSIX path (absolute if outside the project)."""
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    # ---- discovery ---------------------------------------------------
    def iter_manifest_paths(self, under: Path | None = None) -> Iterator[Path]:
        """Yield every ``manifest.toml`` under ``runs/`` (or *under*)."""
        base = under or self.runs_dir
        if not base.is_dir():
            return
        for dirpath, dirnames, filenames in os.walk(base):
            if MANIFEST_FILE in filenames:
                dirnames[:] = []  # a run dir never contains nested runs
                yield Path(dirpath) / MANIFEST_FILE
                continue
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))

    def iter_runs(self, under: Path | None = None) -> Iterator[Manifest]:
        for path in self.iter_manifest_paths(under):
            yield Manifest.load(path)

    def _load_index(self) -> dict[str, str]:
        path = self.state_dir / INDEX_FILE
        try:
            data = load_toml(path)
        except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
            return {}
        runs = data.get("runs", {})
        return {str(k): str(v) for k, v in runs.items()} if isinstance(runs, dict) else {}

    def rebuild_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for path in self.iter_manifest_paths():
            run_id = _peek_run_id(path)
            if run_id:
                index[run_id] = self.rel(path.parent)
        self.save_index(index)
        return index

    def save_index(self, index: dict[str, str]) -> None:
        with suppress(OSError):  # the index is only a cache
            dump_toml(self.state_dir / INDEX_FILE, {"runs": dict(sorted(index.items()))})

    def update_index(self, run_id: str, run_dir: Path | None) -> None:
        index = self._load_index()
        if run_dir is None:
            index.pop(run_id, None)
        else:
            index[run_id] = self.rel(run_dir)
        self.save_index(index)

    def find_by_id(self, run_id: str) -> Manifest | None:
        index = self._load_index()
        cached = index.get(run_id)
        if cached:
            path = self.root / cached / MANIFEST_FILE
            if path.is_file() and _peek_run_id(path) == run_id:
                return Manifest.load(path)
        index = self.rebuild_index()
        cached = index.get(run_id)
        return Manifest.load(self.root / cached / MANIFEST_FILE) if cached else None

    def resolve_run(self, ref: str) -> Manifest:
        """Resolve a run id, a run directory path, or a unique name fragment."""
        ref = ref.strip()
        if not ref:
            raise UsageError("empty run reference")
        if RUN_ID_RE.match(ref):
            found = self.find_by_id(ref)
            if found is None:
                raise UsageError(f"run {ref} not found under {self.runs_dir}")
            return found
        for candidate in (Path(ref), self.root / ref):
            if (candidate / MANIFEST_FILE).is_file():
                return Manifest.load(candidate / MANIFEST_FILE)
        matches = [p for p in self.iter_manifest_paths() if ref in p.parent.name]
        if len(matches) == 1:
            return Manifest.load(matches[0])
        if not matches:
            raise UsageError(f"no run matches {ref!r}")
        shown = "\n  ".join(self.rel(p.parent) for p in matches[:20])
        raise UsageError(f"{ref!r} matches {len(matches)} runs:\n  {shown}")

    # ---- locks -------------------------------------------------------
    @contextmanager
    def _flock(self, name: str) -> Iterator[None]:
        path = (self.state_dir / name).resolve()
        held: dict[Path, int] = _HELD.__dict__.setdefault("depth", {})
        if held.get(path):  # re-entered; a second flock on a new fd would deadlock
            held[path] += 1
            try:
                yield
            finally:
                held[path] -= 1
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            held[path] = 1
            try:
                yield
            finally:
                del held[path]
                fcntl.flock(handle, fcntl.LOCK_UN)

    def id_lock(self) -> AbstractContextManager[None]:
        """Serialize run id allocation and run creation."""
        return self._flock("id.lock")

    def run_lock(self) -> AbstractContextManager[None]:
        """Serialize read-modify-write of run manifests (submit, cancel, retry, sync).

        Callers reload the manifest inside the lock: ``Manifest.save()`` is atomic
        but does not stop a stale in-memory copy from overwriting a newer one.
        """
        return self._flock("run.lock")

    # ---- run id allocation -------------------------------------------
    def next_run_ids(self, count: int, today: datetime | None = None) -> list[str]:
        """Allocate *count* fresh ids. Call while holding :meth:`id_lock`."""
        day = (today or datetime.now().astimezone()).strftime("%Y%m%d")
        highest = 0
        for run_id in self.rebuild_index():
            match = RUN_ID_RE.match(run_id)
            if match and match.group(1) == day:
                highest = max(highest, int(match.group(2)))
        return [f"R{day}-{highest + i:04d}" for i in range(1, count + 1)]


def _peek_run_id(path: Path) -> str:
    try:
        data = load_toml(path)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    run = data.get("run", {})
    return str(run.get("id", "")) if isinstance(run, dict) else ""
