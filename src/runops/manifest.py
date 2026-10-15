"""``manifest.toml`` model, persistence, and state transitions (SPEC §6)."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from runops.errors import UsageError
from runops.util import dump_toml, load_toml, now_iso, parse_iso, tomllib

MANIFEST_FILE = "manifest.toml"
SCHEMA_VERSION = 2


class RunState(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


ACTIVE_STATES = frozenset({RunState.SUBMITTED, RunState.RUNNING})
TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED})

_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.SUBMITTED}),
    RunState.SUBMITTED: frozenset(
        {RunState.RUNNING, RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.RUNNING: frozenset(
        {RunState.SUBMITTED, RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.COMPLETED: frozenset({RunState.ARCHIVED}),
    RunState.FAILED: frozenset({RunState.CREATED, RunState.ARCHIVED}),
    RunState.CANCELLED: frozenset({RunState.CREATED, RunState.ARCHIVED}),
    RunState.ARCHIVED: frozenset(TERMINAL_STATES),
}


class Manifest:
    """A run manifest backed by a plain dict so unknown fields survive."""

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data

    # ---- persistence -------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> Manifest:
        if path.is_dir():
            path = path / MANIFEST_FILE
        try:
            data = load_toml(path)
        except FileNotFoundError:
            raise UsageError(f"{path} not found") from None
        except tomllib.TOMLDecodeError as exc:
            raise UsageError(f"{path}: invalid TOML: {exc}") from None
        schema = data.get("schema")
        if schema != SCHEMA_VERSION:
            raise UsageError(
                f"{path} has manifest schema {schema!r}; this looks like a "
                "runops v1 run. Run `runo migrate-v1` in the project root."
            )
        return cls(path, data)

    def save(self) -> None:
        dump_toml(self.path, self.data)

    @property
    def run_dir(self) -> Path:
        return self.path.parent

    # ---- section helpers ---------------------------------------------
    def section(self, name: str) -> dict[str, Any]:
        value = self.data.setdefault(name, {})
        if not isinstance(value, dict):
            raise UsageError(f"{self.path}: [{name}] must be a table")
        return value

    @property
    def run(self) -> dict[str, Any]:
        return self.section("run")

    @property
    def job(self) -> dict[str, Any]:
        return self.section("job")

    @property
    def id(self) -> str:
        return str(self.run.get("id", ""))

    @property
    def label(self) -> str:
        return str(self.run.get("label", ""))

    @property
    def status(self) -> RunState:
        raw = str(self.run.get("status", "created"))
        try:
            return RunState(raw)
        except ValueError:
            raise UsageError(f"{self.path}: unknown status {raw!r}") from None

    @property
    def scratch(self) -> bool:
        return bool(self.run.get("scratch", False))

    @property
    def pinned(self) -> bool:
        return bool(self.run.get("pinned", False))

    @property
    def why(self) -> str:
        return str(self.run.get("why", ""))

    @property
    def created_at(self) -> str:
        return str(self.run.get("created_at", ""))

    @property
    def case(self) -> str:
        return str(self.section("origin").get("case", ""))

    @property
    def sweep(self) -> str:
        return str(self.section("origin").get("sweep", ""))

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.section("params"))

    @property
    def notes(self) -> list[dict[str, Any]]:
        value = self.data.get("notes", [])
        return list(value) if isinstance(value, list) else []

    @property
    def tags(self) -> list[str]:
        return [str(t) for t in self.run.get("tags", [])]

    @property
    def job_id(self) -> str:
        return str(self.job.get("job_id", ""))

    def created_datetime(self):  # type: ignore[no-untyped-def]
        return parse_iso(self.created_at)

    # ---- mutations ---------------------------------------------------
    def set_status(self, new: RunState) -> None:
        current = self.status
        if new == current:
            return
        if new not in _TRANSITIONS[current]:
            raise UsageError(f"{self.id}: cannot change status from {current.value} to {new.value}")
        self.run["status"] = new.value

    def add_note(self, text: str, by: str) -> None:
        notes = self.data.setdefault("notes", [])
        notes.append({"at": now_iso(), "by": by, "text": text})

    def to_summary(self, root: Path) -> dict[str, Any]:
        """Flat dict for ``list --json`` / ``status --json``."""
        notes = self.notes
        try:
            rel = self.run_dir.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = str(self.run_dir)
        return {
            "id": self.id,
            "status": self.status.value,
            "label": self.label,
            "case": self.case,
            "sweep": self.sweep,
            "created_at": self.created_at,
            "why": self.why,
            "scratch": self.scratch,
            "pinned": self.pinned,
            "tags": self.tags,
            "job_id": self.job_id,
            "run_dir": rel,
            "last_note": str(notes[-1].get("text", "")) if notes else "",
            # Enough for an agent to compare runs without another command.
            "params": self.params,
            "changed_keys": list(self.section("variation").get("changed_keys", [])),
            "parent_run": str(self.section("origin").get("parent_run", "")),
            "exe_hash": str(self.section("simulator").get("exe_hash", "")),
            "input_hash": str(self.section("identity").get("input_hash", "")),
        }
