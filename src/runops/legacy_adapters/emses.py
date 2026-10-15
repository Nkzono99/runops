"""runops v2 project-local adapter for MPIEMSES3D (ported from runops v1).

``runo migrate-v1`` copies this file to ``<project>/adapters/emses.py``. Once
the MPIEMSES3D Python package provides a ``runops.adapters`` entry point named
``emses``, that one wins and the project copy can be deleted.

Conventions (cwd of the job is the run directory):
    input/plasma.toml   rendered from the case's plasma.toml + params
    work/latest/        EMSES output directory (-o)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

INPUT = "input/plasma.toml"
OUTPUT = "work/latest"
ERROR_WORDS = ("error", "segmentation fault", "killed", "oom")
TAIL_BYTES = 64 * 1024


class Adapter:
    name = "emses"

    # ---- required ----------------------------------------------------
    def render_inputs(self, params: dict[str, Any], run_dir: Path) -> list[str]:
        from runops.adapters import toml_override

        path = run_dir / INPUT
        if not path.is_file():
            raise ValueError("case must contain plasma.toml")
        toml_override(path, params)
        (run_dir / OUTPUT).mkdir(parents=True, exist_ok=True)
        return [INPUT]

    def build_command(self, runtime: Any, run_dir: Path) -> list[str]:
        return [str(runtime.executable) or "mpiemses3D", INPUT, "-o", OUTPUT]

    def detect_status(self, run_dir: Path) -> str:
        work = run_dir / "work"
        if not work.is_dir():
            return "unknown"
        for pattern in ("stderr.*.log", "*.err"):
            for log in work.glob(pattern):
                if any(w in _tail(log).lower() for w in ERROR_WORDS):
                    return "failed"
        nstep = _nstep(run_dir)
        last = _last_energy_step(run_dir)
        if nstep and last is not None:
            return "completed" if last >= nstep else "failed"
        return "unknown"

    # ---- optional ----------------------------------------------------
    def case_template(self) -> dict[str, str]:
        return {
            "plasma.toml": (
                "# Put the base EMSES plasma.toml here (e.g. from the MPIEMSES3D cookbook).\n"
                "# Run parameters in case.toml [params] / --set use dotted keys,\n"
                '# e.g. "tmgrid.nx" = 64, "jobcon.nstep" = 10000.\n'
            )
        }

    def pip_packages(self) -> list[str]:
        return [
            "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git",
            "emout",
        ]

    def job_prelude(self, run_dir: Path) -> list[str]:
        return [
            "export EMSES_DEBUG=no",
            f"mkdir -p {OUTPUT}",
            f"rm -f {OUTPUT}/*_0000.h5",
        ]

    def keep_patterns(self) -> list[str]:
        return ["energy*", "stdout.*", "stderr.*", "*.out", "*.err"]

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        config = _config(run_dir)
        tmgrid = config.get("tmgrid", {})
        out = run_dir / OUTPUT
        return {
            "status": self.detect_status(run_dir),
            "nstep": _nstep(run_dir),
            "last_step": _last_energy_step(run_dir),
            "grid": {k: tmgrid[k] for k in ("nx", "ny", "nz", "dt") if k in tmgrid},
            "hdf5_files": len(list(out.glob("*.h5"))) if out.is_dir() else 0,
        }

    def extend_inputs(self, src_run: Path, run_dir: Path, params: dict[str, Any]) -> list[str]:
        """Restart from the source run's SNAPSHOT1 (linked as SNAPSHOT0)."""
        snapshot = next(
            (
                p
                for p in (src_run / OUTPUT / "SNAPSHOT1", src_run / "work" / "SNAPSHOT1")
                if p.is_dir()
            ),
            None,
        )
        if snapshot is None:
            raise ValueError(f"{src_run} has no SNAPSHOT1 to continue from")
        import tomli_w

        rel_parent = snapshot.parent.relative_to(src_run)
        link = run_dir / rel_parent / "SNAPSHOT0"
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(snapshot.resolve(), link)
        path = run_dir / INPUT
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        config.setdefault("jobcon", {})["jobnum"] = [1, 1]
        path.write_text(tomli_w.dumps(config), encoding="utf-8")
        return [INPUT, str(link.relative_to(run_dir))]


def _config(run_dir: Path) -> dict[str, Any]:
    try:
        return tomllib.loads((run_dir / INPUT).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _nstep(run_dir: Path) -> int | None:
    try:
        return int(_config(run_dir).get("jobcon", {}).get("nstep", 0)) or None
    except (TypeError, ValueError):
        return None


def _last_energy_step(run_dir: Path) -> int | None:
    for directory in (run_dir / OUTPUT, run_dir / "work"):
        energy = directory / "energy"
        if not energy.is_file():
            continue
        lines = [line for line in _tail(energy).splitlines() if line.strip()]
        try:
            return int(float(lines[-1].split()[0])) if lines else None
        except (ValueError, IndexError):
            return None
    return None


def _tail(path: Path) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
