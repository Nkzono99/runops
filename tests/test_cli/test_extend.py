"""Tests for the ``runops runs extend`` CLI command."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tomli_w
from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.exceptions import SimctlError
from runops.core.run import RunInfo

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

runner = CliRunner()


def _create_source_run(
    project_root: Path,
    *,
    status: str = "completed",
    include_adapter: bool = True,
) -> Path:
    (project_root / "runops.toml").write_text('[project]\nname = "demo"\n')
    source_dir = project_root / "runs" / "R20260409-0001"
    (source_dir / "input").mkdir(parents=True, exist_ok=True)
    (source_dir / "submit").mkdir(parents=True, exist_ok=True)
    (source_dir / "work").mkdir(parents=True, exist_ok=True)
    with open(source_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(
            {
                "run": {
                    "id": "R20260409-0001",
                    "display_name": "baseline",
                    "status": status,
                },
                "origin": {"case": "beam_case"},
                "classification": {"tags": ["production"]},
                "simulator": {
                    "adapter": "emses" if include_adapter else "",
                    "name": "emses",
                },
                "launcher": {"name": "slurm_srun"},
                "simulator_source": {"git_commit": "abc123"},
                "job": {
                    "partition": "debug",
                    "nodes": 2,
                    "ntasks": 8,
                    "walltime": "02:00:00",
                },
                "params_snapshot": {"nstep": 1000, "dt": 0.1},
            },
            f,
        )
    (source_dir / "input" / "params.json").write_text(
        '{"nstep": 1000}',
        encoding="utf-8",
    )
    (source_dir / "input" / "restart").mkdir(parents=True, exist_ok=True)
    (source_dir / "input" / "restart" / "snapshot.dat").write_text(
        "snapshot",
        encoding="utf-8",
    )
    (source_dir / "input" / "mesh.dat").write_text("mesh", encoding="utf-8")
    (source_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n"
        "#SBATCH --job-name=R20260409-0001\n"
        f"#SBATCH --output={source_dir}/work/%j.out\n"
        f"cd {source_dir}\n",
        encoding="utf-8",
    )
    return source_dir


def test_extend_creates_continuation_run_and_copies_artifacts(tmp_path: Path) -> None:
    source_dir = _create_source_run(tmp_path)
    new_dir = tmp_path / "runs" / "R20260409-0002"
    project = SimpleNamespace(simulators={"emses": {}})

    class FakeAdapter:
        def setup_continuation(
            self,
            *,
            source_dir: Path,
            new_dir: Path,
            nstep_override: int | None,
        ) -> dict[str, str]:
            assert source_dir.name == "R20260409-0001"
            assert new_dir.name == "R20260409-0002"
            assert nstep_override == 2000
            return {"restart": "linked"}

    with (
        patch("runops.cli.extend.load_project", return_value=project),
        patch("runops.adapters.registry.load_from_config"),
        patch("runops.adapters.registry.get", return_value=FakeAdapter),
        patch(
            "runops.cli.extend.collect_existing_run_ids",
            return_value={"R20260409-0001"},
        ),
        patch(
            "runops.cli.extend.create_run",
            return_value=RunInfo(
                run_id="R20260409-0002",
                run_dir=new_dir,
                display_name="extend_R20260409-0001",
                created_at="2026-04-09T00:00:00+00:00",
                params={"nstep": 1000, "dt": 0.1},
            ),
        ),
    ):
        result = runner.invoke(
            app,
            ["runs", "extend", "--nstep", "2000", str(source_dir)],
        )

    assert result.exit_code == 0, result.output
    assert "Created continuation run: R20260409-0002" in result.output
    assert "Source: R20260409-0001" in result.output
    assert "restart: linked" in result.output
    assert (new_dir / "input" / "params.json").read_text(encoding="utf-8") == (
        '{"nstep": 1000}'
    )
    assert (new_dir / "input" / "mesh.dat").read_text(encoding="utf-8") == "mesh"
    assert (new_dir / "input" / "restart" / "snapshot.dat").read_text(
        encoding="utf-8"
    ) == "snapshot"
    assert (new_dir / "submit" / "job.sh").exists()
    new_job = (new_dir / "submit" / "job.sh").read_text(encoding="utf-8")
    assert str(source_dir) not in new_job
    assert "R20260409-0001" not in new_job
    assert str(new_dir) in new_job
    assert "R20260409-0002" in new_job
    assert (new_dir / "work").is_dir()

    with open(new_dir / "manifest.toml", "rb") as f:
        manifest = tomllib.load(f)
    assert manifest["origin"]["parent_run"] == "R20260409-0001"
    assert manifest["job"]["partition"] == "debug"
    assert manifest["run"]["status"] == "created"


def test_extend_warns_for_non_completed_source_and_surfaces_auto_submit_failure(
    tmp_path: Path,
) -> None:
    source_dir = _create_source_run(tmp_path, status="created")
    new_dir = tmp_path / "runs" / "R20260409-0002"
    project = SimpleNamespace(simulators={"emses": {}})

    class FakeAdapter:
        def setup_continuation(
            self,
            *,
            source_dir: Path,
            new_dir: Path,
            nstep_override: int | None,
        ) -> dict[str, str]:
            return {}

    with (
        patch("runops.cli.extend.load_project", return_value=project),
        patch("runops.adapters.registry.load_from_config"),
        patch("runops.adapters.registry.get", return_value=FakeAdapter),
        patch(
            "runops.cli.extend.collect_existing_run_ids",
            return_value={"R20260409-0001"},
        ),
        patch(
            "runops.cli.extend.create_run",
            return_value=RunInfo(
                run_id="R20260409-0002",
                run_dir=new_dir,
                display_name="extend_R20260409-0001",
                created_at="2026-04-09T00:00:00+00:00",
                params={"nstep": 1000, "dt": 0.1},
            ),
        ),
        patch("runops.cli.submit._submit_single_run", return_value=None),
    ):
        result = runner.invoke(app, ["runs", "extend", "--run", str(source_dir)])

    assert result.exit_code == 1
    assert "Continuation is typically from completed runs." in result.output
    assert "Warning: auto-submit failed" in result.output


def test_extend_surfaces_manifest_read_errors(tmp_path: Path) -> None:
    with (
        patch("runops.cli.extend.resolve_run_or_cwd", return_value=tmp_path),
        patch(
            "runops.cli.extend.read_manifest",
            side_effect=SimctlError("missing manifest"),
        ),
    ):
        result = runner.invoke(app, ["runs", "extend"])

    assert result.exit_code == 1
    assert "Error: missing manifest" in result.output


def test_extend_surfaces_project_lookup_errors(tmp_path: Path) -> None:
    source_dir = _create_source_run(tmp_path)

    with patch(
        "runops.cli.extend.load_project",
        side_effect=SimctlError("project config is broken"),
    ):
        result = runner.invoke(app, ["runs", "extend", str(source_dir)])

    assert result.exit_code == 1
    assert "Error: project config is broken" in result.output


def test_extend_surfaces_adapter_loading_errors(tmp_path: Path) -> None:
    source_dir = _create_source_run(tmp_path)
    project = SimpleNamespace(simulators={"emses": {}})

    with (
        patch("runops.cli.extend.load_project", return_value=project),
        patch("runops.adapters.registry.load_from_config"),
        patch(
            "runops.adapters.registry.get",
            side_effect=KeyError("emses adapter missing"),
        ),
    ):
        result = runner.invoke(app, ["runs", "extend", str(source_dir)])

    assert result.exit_code == 1
    assert "Error loading adapter 'emses'" in result.output


def test_extend_falls_back_to_simulator_name_when_adapter_is_missing(
    tmp_path: Path,
) -> None:
    source_dir = _create_source_run(tmp_path, include_adapter=False)
    new_dir = tmp_path / "runs" / "R20260409-0002"
    project = SimpleNamespace(simulators={"emses": {}})

    class FakeAdapter:
        def setup_continuation(
            self,
            *,
            source_dir: Path,
            new_dir: Path,
            nstep_override: int | None,
        ) -> dict[str, str]:
            return {}

    with (
        patch("runops.cli.extend.load_project", return_value=project),
        patch("runops.adapters.registry.load_from_config"),
        patch("runops.adapters.registry.get", return_value=FakeAdapter) as mock_get,
        patch(
            "runops.cli.extend.collect_existing_run_ids",
            return_value={"R20260409-0001"},
        ),
        patch(
            "runops.cli.extend.create_run",
            return_value=RunInfo(
                run_id="R20260409-0002",
                run_dir=new_dir,
                display_name="extend_R20260409-0001",
                created_at="2026-04-09T00:00:00+00:00",
                params={"nstep": 1000},
            ),
        ),
    ):
        result = runner.invoke(app, ["runs", "extend", str(source_dir)])

    assert result.exit_code == 0, result.output
    mock_get.assert_called_once_with("emses")


def test_extend_surfaces_run_creation_errors(tmp_path: Path) -> None:
    source_dir = _create_source_run(tmp_path)
    project = SimpleNamespace(simulators={"emses": {}})

    class FakeAdapter:
        pass

    with (
        patch("runops.cli.extend.load_project", return_value=project),
        patch("runops.adapters.registry.load_from_config"),
        patch("runops.adapters.registry.get", return_value=FakeAdapter),
        patch(
            "runops.cli.extend.collect_existing_run_ids",
            return_value={"R20260409-0001"},
        ),
        patch(
            "runops.cli.extend.create_run",
            side_effect=SimctlError("run id collision"),
        ),
    ):
        result = runner.invoke(app, ["runs", "extend", str(source_dir)])

    assert result.exit_code == 1
    assert "Error creating run: run id collision" in result.output


def test_extend_surfaces_adapter_continuation_errors(tmp_path: Path) -> None:
    source_dir = _create_source_run(tmp_path)
    new_dir = tmp_path / "runs" / "R20260409-0002"
    project = SimpleNamespace(simulators={"emses": {}})

    class FakeAdapter:
        def setup_continuation(
            self,
            *,
            source_dir: Path,
            new_dir: Path,
            nstep_override: int | None,
        ) -> dict[str, str]:
            raise RuntimeError("snapshot missing")

    with (
        patch("runops.cli.extend.load_project", return_value=project),
        patch("runops.adapters.registry.load_from_config"),
        patch("runops.adapters.registry.get", return_value=FakeAdapter),
        patch(
            "runops.cli.extend.collect_existing_run_ids",
            return_value={"R20260409-0001"},
        ),
        patch(
            "runops.cli.extend.create_run",
            return_value=RunInfo(
                run_id="R20260409-0002",
                run_dir=new_dir,
                display_name="extend_R20260409-0001",
                created_at="2026-04-09T00:00:00+00:00",
                params={"nstep": 1000},
            ),
        ),
    ):
        result = runner.invoke(app, ["runs", "extend", str(source_dir)])

    assert result.exit_code == 1
    assert "Error in adapter continuation setup: snapshot missing" in result.output
