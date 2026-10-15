"""runops v2 project-local adapter for BEACH (ported from runops v1).

``runo migrate-v1`` copies this file to ``<project>/adapters/beach.py``. Once
the BEACH Python package (``beach-bem``) provides a ``runops.adapters`` entry
point named ``beach``, that one wins and the project copy can be deleted.

Conventions (cwd of the job is the run directory):
    input/beach.toml    rendered from the case's beach.toml + params
    work/latest/        BEACH output directory ([output].dir)
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

INPUT = "input/beach.toml"
OUTPUT = "work/latest"
ERROR_WORDS = ("error", "fatal", "killed", "oom")
BATCH_RE = re.compile(r"\bbatch\s+(\d+)\s*/\s*(\d+)\b", re.IGNORECASE)
TAIL_BYTES = 256 * 1024


class Adapter:
    name = "beach"

    # ---- required ----------------------------------------------------
    def render_inputs(self, params: dict[str, Any], run_dir: Path) -> list[str]:
        from runops.adapters import toml_override

        path = run_dir / INPUT
        template = run_dir / "input/beach_template.toml"
        if not path.is_file() and template.is_file():
            shutil.move(str(template), str(path))
        if not path.is_file():
            raise ValueError("case must contain beach.toml")
        config = toml_override(path, {**params, "output.dir": OUTPUT})
        written = [INPUT]
        obj = str(config.get("mesh", {}).get("obj_path", ""))
        if obj and Path(obj).is_absolute() and Path(obj).is_file():
            dest = run_dir / "input" / Path(obj).name
            shutil.copy2(obj, dest)
            toml_override(path, {"mesh.obj_path": f"input/{dest.name}"})
            written.append(f"input/{dest.name}")
        (run_dir / OUTPUT).mkdir(parents=True, exist_ok=True)
        return written

    def build_command(self, runtime: Any, run_dir: Path) -> list[str]:
        return [str(runtime.executable) or "beach", INPUT]

    def detect_status(self, run_dir: Path) -> str:
        work = run_dir / "work"
        job_id = _job_id(run_dir)
        logs = [work / f"stderr.{job_id}.log", work / f"{job_id}.err"] if job_id else []
        logs = [p for p in logs if p.is_file()] or sorted(
            [*work.glob("stderr.*.log"), *work.glob("*.err")],
            key=lambda p: p.stat().st_mtime,
        )[-1:]
        if any(any(w in _tail(p).lower() for w in ERROR_WORDS) for p in logs):
            return "failed"
        if _summary_file(run_dir) is not None:
            return "completed"
        return "failed" if work.is_dir() and any(work.iterdir()) else "unknown"

    # ---- optional ----------------------------------------------------
    def case_template(self) -> dict[str, str]:
        return {
            "beach.toml": (
                "# Base BEACH configuration. [output].dir is set by the adapter.\n"
                "# Override values with dotted keys, e.g. --set sim.batch_count=200\n\n"
                "[sim]\n"
                "dt = 1.0e-6\n"
                "batch_count = 100\n\n"
                "[mesh]\n"
                '# obj_path = "mesh.obj"\n'
            )
        }

    def pip_packages(self) -> list[str]:
        return ["beach-bem"]

    def keep_patterns(self) -> list[str]:
        return ["summary.txt", "charges.csv", "stdout.*", "stderr.*", "*.out", "*.err"]

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        summary: dict[str, Any] = {"status": self.detect_status(run_dir)}
        path = _summary_file(run_dir)
        if path is not None:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                key, sep, value = line.partition("=")
                if not sep:
                    continue
                value = value.strip()
                try:
                    summary[key.strip()] = int(value)
                except ValueError:
                    try:
                        summary[key.strip()] = float(value)
                    except ValueError:
                        summary[key.strip()] = value
        progress = _progress(run_dir)
        if progress is not None:
            summary["batch"], summary["batch_count"] = progress
        return summary


def _job_id(run_dir: Path) -> str:
    try:
        from runops.util import tomllib

        data = tomllib.loads((run_dir / "manifest.toml").read_text(encoding="utf-8"))
        return str(data.get("job", {}).get("job_id", ""))
    except Exception:  # status detection must not crash
        return ""


def _summary_file(run_dir: Path) -> Path | None:
    work = run_dir / "work"
    for directory in (work / "latest", work / "outputs" / "latest", work / "outputs", work):
        if (directory / "summary.txt").is_file():
            return directory / "summary.txt"
    return None


def _progress(run_dir: Path) -> tuple[int, int] | None:
    work = run_dir / "work"
    logs = sorted(
        [*work.glob("stdout.*.log"), *work.glob("*.out")], key=lambda p: p.stat().st_mtime
    )
    if not logs:
        return None
    matches = BATCH_RE.findall(_tail(logs[-1]))
    return (int(matches[-1][0]), int(matches[-1][1])) if matches else None


def _tail(path: Path) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
