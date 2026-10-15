"""Built-in ``generic`` adapter (SPEC §8.4).

* Text files in ``input/`` containing Jinja2 markers are rendered with the
  run params (dotted keys are also exposed as nested objects).
* ``[simulators.X].command`` is the program command, split with shlex;
  ``{executable}`` is replaced by the resolved executable.
* ``[simulators.X].success_marker``: when set, ``work/<marker>`` must exist
  for a run to count as completed; otherwise Slurm's state decides.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import jinja2

from runops.adapters.base import RuntimeInfo, SimulatorAdapter, exe_str, set_dotted


class GenericAdapter(SimulatorAdapter):
    name = "generic"

    def __init__(self) -> None:
        self.sim_config: dict[str, Any] = {}

    def configure(self, sim_config: dict[str, Any]) -> None:
        self.sim_config = dict(sim_config)

    def case_template(self) -> dict[str, str]:
        return {
            "input.txt": "# rendered with Jinja2, e.g. value = {{ params['x'] | default(1) }}\n"
        }

    def render_inputs(self, params: dict[str, Any], run_dir: Path) -> list[str]:
        nested: dict[str, Any] = {}
        for key, value in params.items():
            try:
                set_dotted(nested, key, value)
            except ValueError:
                nested[key] = value
        env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
        written: list[str] = []
        input_dir = run_dir / "input"
        for path in sorted(p for p in input_dir.rglob("*") if p.is_file()):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "{{" not in text and "{%" not in text:
                continue
            try:
                rendered = env.from_string(text).render(params=params, **nested)
            except jinja2.TemplateError as exc:
                raise ValueError(f"{path.name}: template error: {exc}") from exc
            path.write_text(rendered, encoding="utf-8")
            written.append(path.relative_to(run_dir).as_posix())
        return written

    def build_command(self, runtime: RuntimeInfo, run_dir: Path) -> list[str]:
        command = str(self.sim_config.get("command", "")).strip()
        executable = exe_str(runtime.executable)
        if not command:
            return [executable]
        return [part.replace("{executable}", executable) for part in shlex.split(command)]

    def detect_status(self, run_dir: Path) -> str:
        marker = str(self.sim_config.get("success_marker", "")).strip()
        if not marker:
            return "unknown"
        return "completed" if (run_dir / "work" / marker).exists() else "failed"
