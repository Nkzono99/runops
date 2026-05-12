"""End-to-end coverage for bootstrap and knowledge workflows."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.knowledge_source import load_knowledge_config

runner = CliRunner()


def _fake_bootstrap_environment(
    project_dir: Path,
    _sim_names: list[str],
    _runops_package: str,
    created: list[str],
    skipped: list[str],
) -> None:
    """Create the minimum bootstrap artifacts used by E2E tests."""
    venv_dir = project_dir / ".venv"
    if venv_dir.exists():
        skipped.append(".venv")
    else:
        (venv_dir / "Scripts").mkdir(parents=True, exist_ok=True)
        created.append(".venv")


def _init_project(
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
    simulators: Sequence[str] = (),
) -> None:
    """Initialize a test project with a lightweight bootstrap stub."""
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        _fake_bootstrap_environment,
    )
    result = runner.invoke(
        app,
        ["init", *simulators, "-y", "--path", str(project_dir)],
    )
    assert result.exit_code == 0, result.output


def _patch_project_cwd(
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
) -> None:
    """Make knowledge CLI commands resolve the given project as cwd."""
    monkeypatch.setattr("runops.cli.knowledge.Path.cwd", lambda: project_dir)


def _write_profile_knowledge_repo(root: Path, profiles: Sequence[str]) -> None:
    """Create a minimal shared knowledge repository layout."""
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Shared knowledge\n", encoding="utf-8")

    manifest_blocks: list[str] = []
    for profile_name in profiles:
        (root / "profiles" / f"{profile_name}.md").write_text(
            f"# {profile_name}\n",
            encoding="utf-8",
        )
        (root / "docs" / f"{profile_name}.md").write_text(
            f"# {profile_name} guide\n",
            encoding="utf-8",
        )
        manifest_blocks.append(
            "\n".join(
                [
                    f"[profiles.{profile_name}]",
                    (
                        "imports = ["
                        f'"profiles/{profile_name}.md", "docs/{profile_name}.md"'
                        "]"
                    ),
                    "",
                ]
            )
        )

    (root / "entrypoints.toml").write_text(
        "\n".join(manifest_blocks),
        encoding="utf-8",
    )


def _run_git(args: Sequence[str], cwd: Path) -> None:
    """Run git and fail the test with stderr when it errors."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _create_git_remote(
    base_dir: Path,
    repo_name: str,
    profiles: Sequence[str],
) -> Path:
    """Create a local bare git repository that hosts a knowledge source."""
    worktree = base_dir / f"{repo_name}-worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    _run_git(["init"], worktree)
    _run_git(["config", "user.name", "Simctl Tests"], worktree)
    _run_git(["config", "user.email", "runops-tests@example.com"], worktree)

    _write_profile_knowledge_repo(worktree, profiles)
    _run_git(["add", "."], worktree)
    _run_git(["commit", "-m", "Seed knowledge"], worktree)
    _run_git(["branch", "-M", "main"], worktree)

    remote = base_dir / f"{repo_name}.git"
    _run_git(["clone", "--bare", str(worktree), str(remote)], base_dir)
    return remote


def _assert_minimum_bootstrap_layout(project_dir: Path) -> None:
    """Verify the minimum scaffold expected from init/setup bootstrap."""
    expected_paths = (
        project_dir / "runops.toml",
        project_dir / "simulators.toml",
        project_dir / "launchers.toml",
        project_dir / "campaign.toml",
        project_dir / "cases",
        project_dir / "runs",
        project_dir / "research" / "agenda.md",
        project_dir / ".runops",
        project_dir / ".claude" / "settings.json",
        project_dir / ".claude" / "rules",
        project_dir / ".claude" / "skills",
        project_dir / ".agents" / "skills",
        project_dir / ".codex" / "config.toml",
        project_dir / ".codex" / "rules" / "runops.rules",
        project_dir / "CLAUDE.md",
        project_dir / "AGENTS.md",
        project_dir / "cases" / "AGENTS.md",
        project_dir / "runs" / "AGENTS.md",
    )
    for expected_path in expected_paths:
        assert expected_path.exists(), expected_path
    # PreToolUse hooks are no longer scaffolded; their intent lives in
    # .claude/rules/runops-workflow.md.
    hooks_dir = project_dir / ".claude" / "hooks"
    if hooks_dir.exists():
        assert not any(hooks_dir.iterdir()), hooks_dir


@pytest.mark.parametrize("simulators", [(), ("emses",)])
def test_e2e_init_minimal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    simulators: Sequence[str],
) -> None:
    """Init creates the minimum scaffold and stays doctor-clean."""
    project_dir = tmp_path / "init-project"

    _init_project(monkeypatch, project_dir, simulators)
    _assert_minimum_bootstrap_layout(project_dir)

    imports_path = project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    assert imports_path.is_file()
    assert "@.runops/knowledge/runops/agent-user-guide.md" in imports_path.read_text(
        encoding="utf-8"
    )

    claude_md = (project_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "@.runops/knowledge/enabled/imports.md" in claude_md
    agents_md = (project_dir / "AGENTS.md").read_text(encoding="utf-8")
    assert ".runops/knowledge/enabled/imports.md" in agents_md
    assert "$new-case" in agents_md

    settings = json.loads(
        (project_dir / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert "permissions" in settings
    assert "Edit(/campaign.toml)" in settings["permissions"]["allow"]
    assert "Edit(/tools/runops/**)" not in settings["permissions"]["allow"]
    assert "Bash(runo runs submit*)" in settings["permissions"]["allow"]
    assert "Bash(runops runs submit*)" in settings["permissions"]["allow"]
    assert "Bash(runo runs submit*)" not in settings["permissions"]["ask"]
    assert "Bash(runops runs submit*)" not in settings["permissions"]["ask"]
    assert "Write(/runops.toml)" in settings["permissions"]["ask"]
    assert "Write(/SITE.md)" in settings["permissions"]["deny"]
    # PreToolUse hooks were intentionally removed (moved to rules); the
    # generated settings.json must not declare them.
    assert "hooks" not in settings

    simulators_toml = (project_dir / "simulators.toml").read_text(encoding="utf-8")
    campaign_toml = (project_dir / "campaign.toml").read_text(encoding="utf-8")
    if simulators:
        assert "[simulators.emses]" in simulators_toml
        assert 'simulator = "emses"' in campaign_toml
    else:
        assert "[simulators]" in simulators_toml

    with pytest.MonkeyPatch.context() as doctor_patch:
        doctor_patch.setattr(
            "runops.cli.init.shutil.which",
            lambda _name: "/usr/bin/sbatch",
        )
        doctor = runner.invoke(app, ["doctor", str(project_dir)])

    assert doctor.exit_code == 0, doctor.output
    assert "All checks passed" in doctor.output


def test_e2e_setup_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup bootstraps an existing project and can be re-run safely."""
    project_dir = tmp_path / "setup-project"
    project_dir.mkdir()
    simproject_before = (
        "#:schema https://example.test/simproject.json\n"
        "[project]\n"
        'name = "setup-project"\n'
        'description = "existing"\n'
    )
    claude_before = "# existing claude instructions\n"

    (project_dir / "runops.toml").write_text(simproject_before, encoding="utf-8")
    (project_dir / "simulators.toml").write_text("[simulators]\n", encoding="utf-8")
    (project_dir / "launchers.toml").write_text(
        '[launchers.srun]\ntype = "srun"\nuse_slurm_ntasks = true\n',
        encoding="utf-8",
    )
    (project_dir / "CLAUDE.md").write_text(claude_before, encoding="utf-8")

    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        _fake_bootstrap_environment,
    )

    first = runner.invoke(app, ["setup", "--path", str(project_dir)])
    imports_path = project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    imports_after_first = imports_path.read_text(encoding="utf-8")
    second = runner.invoke(app, ["setup", "--path", str(project_dir)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Skipped" in second.output

    assert (project_dir / ".venv").is_dir()
    assert not (project_dir / "tools" / "runops").exists()
    assert imports_path.is_file()

    assert (project_dir / "runops.toml").read_text(
        encoding="utf-8"
    ) == simproject_before
    assert (project_dir / "CLAUDE.md").read_text(encoding="utf-8") == claude_before

    imports_after_second = imports_path.read_text(encoding="utf-8")
    assert imports_after_first == imports_after_second


def test_e2e_knowledge_path_attach_sync_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path knowledge source can be attached, synced, rendered, and inspected."""
    project_dir = tmp_path / "path-project"
    _init_project(monkeypatch, project_dir)

    kb_dir = tmp_path / "shared-kb"
    _write_profile_knowledge_repo(kb_dir, ["common-analysis"])
    _patch_project_cwd(monkeypatch, project_dir)

    attach = runner.invoke(
        app,
        [
            "knowledge",
            "source",
            "attach",
            "path",
            "shared-kb",
            str(kb_dir),
            "--profiles",
            "common-analysis",
            "--no-sync",
        ],
    )
    sync = runner.invoke(app, ["knowledge", "source", "sync"])
    render = runner.invoke(app, ["knowledge", "source", "render"])
    status = runner.invoke(app, ["knowledge", "source", "status"])

    assert attach.exit_code == 0, attach.output
    assert sync.exit_code == 0, sync.output
    assert render.exit_code == 0, render.output
    assert status.exit_code == 0, status.output

    mounted_source = project_dir / "refs" / "knowledge" / "shared-kb"
    assert mounted_source.exists()

    imports_path = project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    imports = imports_path.read_text(encoding="utf-8")
    assert "@refs/knowledge/shared-kb/profiles/common-analysis.md" in imports
    assert "@refs/knowledge/shared-kb/docs/common-analysis.md" in imports
    assert "shared-kb" in status.output
    assert "ready" in status.output


def test_e2e_knowledge_git_attach_sync_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A git knowledge source can be cloned, rendered, and synced repeatedly."""
    project_dir = tmp_path / "git-project"
    _init_project(monkeypatch, project_dir)

    remote = _create_git_remote(tmp_path, "lab-kb", ["common-analysis"])
    _patch_project_cwd(monkeypatch, project_dir)

    attach = runner.invoke(
        app,
        [
            "knowledge",
            "source",
            "attach",
            "git",
            "lab-kb",
            str(remote),
            "--profiles",
            "common-analysis",
            "--no-sync",
        ],
    )
    first_sync = runner.invoke(app, ["knowledge", "source", "sync"])
    render = runner.invoke(app, ["knowledge", "source", "render"])
    second_sync = runner.invoke(app, ["knowledge", "source", "sync"])

    assert attach.exit_code == 0, attach.output
    assert first_sync.exit_code == 0, first_sync.output
    assert render.exit_code == 0, render.output
    assert second_sync.exit_code == 0, second_sync.output

    mounted_source = project_dir / "refs" / "knowledge" / "lab-kb"
    assert (mounted_source / ".git").is_dir()
    imports = (
        project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    ).read_text(encoding="utf-8")
    assert "@refs/knowledge/lab-kb/profiles/common-analysis.md" in imports
    assert "@refs/knowledge/lab-kb/docs/common-analysis.md" in imports
    assert "updated" in second_sync.output


def test_e2e_profile_enable_disable_rerender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile toggles update both config and rendered imports."""
    project_dir = tmp_path / "profile-project"
    _init_project(monkeypatch, project_dir)

    kb_dir = tmp_path / "shared-kb"
    _write_profile_knowledge_repo(kb_dir, ["common-analysis", "emses-basic"])
    _patch_project_cwd(monkeypatch, project_dir)

    attach = runner.invoke(
        app,
        [
            "knowledge",
            "source",
            "attach",
            "path",
            "shared-kb",
            str(kb_dir),
            "--profiles",
            "common-analysis",
        ],
    )
    assert attach.exit_code == 0, attach.output
    initial_render = runner.invoke(app, ["knowledge", "source", "render"])
    assert initial_render.exit_code == 0, initial_render.output

    baseline_imports = (
        project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    ).read_text(encoding="utf-8")
    assert "@refs/knowledge/shared-kb/profiles/common-analysis.md" in baseline_imports
    assert "@refs/knowledge/shared-kb/profiles/emses-basic.md" not in baseline_imports

    enable = runner.invoke(
        app,
        ["knowledge", "profile", "enable", "shared-kb", "emses-basic"],
    )
    after_enable = (
        project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    ).read_text(encoding="utf-8")
    disable = runner.invoke(
        app,
        ["knowledge", "profile", "disable", "shared-kb", "common-analysis"],
    )
    after_disable = (
        project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    ).read_text(encoding="utf-8")

    assert enable.exit_code == 0, enable.output
    assert disable.exit_code == 0, disable.output
    assert "@refs/knowledge/shared-kb/profiles/common-analysis.md" in after_enable
    assert "@refs/knowledge/shared-kb/profiles/emses-basic.md" in after_enable
    assert "@refs/knowledge/shared-kb/profiles/common-analysis.md" not in after_disable
    assert "@refs/knowledge/shared-kb/profiles/emses-basic.md" in after_disable

    config = load_knowledge_config(project_dir)
    assert config is not None
    assert config.sources[0].profiles == ["emses-basic"]


def test_e2e_doctor_after_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor passes after init plus knowledge bootstrap on a fresh project."""
    project_dir = tmp_path / "doctor-project"
    _init_project(monkeypatch, project_dir, ("emses",))

    kb_dir = tmp_path / "shared-kb"
    _write_profile_knowledge_repo(kb_dir, ["common-analysis"])
    _patch_project_cwd(monkeypatch, project_dir)

    attach = runner.invoke(
        app,
        [
            "knowledge",
            "source",
            "attach",
            "path",
            "shared-kb",
            str(kb_dir),
            "--profiles",
            "common-analysis",
        ],
    )
    render = runner.invoke(app, ["knowledge", "source", "render"])

    assert attach.exit_code == 0, attach.output
    assert render.exit_code == 0, render.output
    assert (project_dir / ".claude" / "settings.json").is_file()
    assert (project_dir / ".runops" / "knowledge" / "enabled" / "imports.md").is_file()

    with pytest.MonkeyPatch.context() as doctor_patch:
        doctor_patch.setattr(
            "runops.cli.init.shutil.which",
            lambda _name: "/usr/bin/sbatch",
        )
        doctor = runner.invoke(app, ["doctor", str(project_dir)])

    assert doctor.exit_code == 0, doctor.output
    assert "[PASS] runops.toml is valid" in doctor.output
    assert "[PASS] simulators.toml found" in doctor.output
    assert "[PASS] launchers.toml found" in doctor.output
    assert "[PASS] sbatch is available" in doctor.output
    assert "[PASS] No duplicate run_ids" in doctor.output
