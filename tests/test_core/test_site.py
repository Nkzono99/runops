"""Tests for site profile loading and SiteProfile dataclass."""

from __future__ import annotations

from pathlib import Path

from runops.core.codex_plugin import CodexPluginRecommendation
from runops.core.site import (
    MOCK_SITE,
    STANDARD_SITE,
    SiteProfile,
    load_site_profile,
    save_site_profile,
)

# ---------------------------------------------------------------------------
# SiteProfile dataclass
# ---------------------------------------------------------------------------


class TestSiteProfile:
    """Tests for the SiteProfile dataclass."""

    def test_standard_site_defaults(self) -> None:
        assert STANDARD_SITE.name == "standard"
        assert STANDARD_SITE.scheduler == "slurm"
        assert STANDARD_SITE.resource_style == "standard"
        assert STANDARD_SITE.modules == []
        assert STANDARD_SITE.stdout_format is None
        assert STANDARD_SITE.stderr_format is None

    def test_mock_site_values(self) -> None:
        assert MOCK_SITE.name == "mock"
        assert MOCK_SITE.resource_style == "standard"
        assert "mock/compiler" in MOCK_SITE.modules
        assert "mock/mpi" in MOCK_SITE.modules

    def test_modules_for_no_simulator(self) -> None:
        """modules_for returns site-wide modules when simulator has no extras."""
        site = SiteProfile(modules=["base/mod"])
        assert site.modules_for("unknown_sim") == ["base/mod"]

    def test_modules_for_with_simulator(self) -> None:
        """modules_for merges site-wide and simulator-specific modules."""
        site = SiteProfile(
            modules=["intel/2023.2", "intelmpi/2023.2"],
            simulator_modules={
                "emses": ["hdf5/1.12", "fftw/3.3"],
            },
        )
        result = site.modules_for("emses")
        assert result == ["intel/2023.2", "intelmpi/2023.2", "hdf5/1.12", "fftw/3.3"]

    def test_modules_for_no_duplicates(self) -> None:
        """modules_for does not duplicate modules already in site-wide list."""
        site = SiteProfile(
            modules=["intel/2023.2"],
            simulator_modules={
                "emses": ["intel/2023.2", "hdf5/1.12"],
            },
        )
        result = site.modules_for("emses")
        assert result == ["intel/2023.2", "hdf5/1.12"]

    def test_mock_site_modules_for(self) -> None:
        result = MOCK_SITE.modules_for("test_sim")
        assert "mock/compiler" in result
        assert "mock/mpi" in result
        assert "mock/hdf5" in result


# ---------------------------------------------------------------------------
# load_site_profile
# ---------------------------------------------------------------------------


class TestLoadSiteProfile:
    """Tests for loading site profiles from files."""

    def test_loads_site_toml(self, tmp_path: Path) -> None:
        """site.toml is the primary source."""
        site_toml = tmp_path / "site.toml"
        site_toml.write_text(
            "[site]\n"
            'name = "testsite"\n'
            'scheduler = "pbs"\n'
            'resource_style = "rsc"\n'
            'modules = ["mod/a", "mod/b"]\n'
            'stdout = "stdout.%J.log"\n'
            'stderr = "stderr.%J.log"\n'
            'extra_pbs = ["-j oe"]\n'
            'pbs_group = "testgrp"\n'
            "\n"
            "[site.env]\n"
            'FOO = "bar"\n'
            "\n"
            "[site.simulators.emses]\n"
            'modules = ["hdf5/1.12"]\n'
        )
        # Also create runops.toml so it looks like a project
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')

        profile = load_site_profile(tmp_path)
        assert profile.name == "testsite"
        assert profile.scheduler == "pbs"
        assert profile.resource_style == "rsc"
        assert profile.modules == ["mod/a", "mod/b"]
        assert profile.stdout_format == "stdout.%J.log"
        assert profile.stderr_format == "stderr.%J.log"
        assert profile.extra_pbs == ["-j oe"]
        assert profile.pbs_group == "testgrp"
        assert profile.env == {"FOO": "bar"}
        assert profile.simulator_modules == {"emses": ["hdf5/1.12"]}

    def test_loads_codex_plugin_recommendations(self, tmp_path: Path) -> None:
        """site.toml may recommend external Codex plugins."""
        site_toml = tmp_path / "site.toml"
        site_toml.write_text(
            "[site]\n"
            'name = "testsite"\n'
            "\n"
            "[site.codex_plugins.test-plugin]\n"
            'display_name = "Test Plugin"\n'
            'visibility = "private-or-gated"\n'
            'reason = "Site-specific workflow guidance."\n'
            'install_hint = "codex plugin add test-plugin@test-marketplace"\n'
            'activation_hint = "Start a new Codex thread."\n',
            encoding="utf-8",
        )

        profile = load_site_profile(tmp_path)

        assert len(profile.codex_plugins) == 1
        plugin = profile.codex_plugins[0]
        assert plugin.name == "test-plugin"
        assert plugin.display_name == "Test Plugin"
        assert plugin.visibility == "private-or-gated"
        assert "codex plugin add" in plugin.install_hint

    def test_fallback_to_launchers_toml(self, tmp_path: Path) -> None:
        """Legacy: extract site config from launchers.toml if no site.toml."""
        launchers_toml = tmp_path / "launchers.toml"
        launchers_toml.write_text(
            "[launchers.srun]\n"
            'type = "srun"\n'
            "use_slurm_ntasks = true\n"
            'resource_style = "rsc"\n'
            'modules = ["intel/2023.2"]\n'
            'stdout = "stdout.%J.log"\n'
        )

        profile = load_site_profile(tmp_path)
        assert profile.resource_style == "rsc"
        assert profile.modules == ["intel/2023.2"]
        assert profile.stdout_format == "stdout.%J.log"
        assert "legacy:" in profile.name

    def test_fallback_to_standard(self, tmp_path: Path) -> None:
        """No site.toml and no site keys in launchers.toml → STANDARD_SITE."""
        launchers_toml = tmp_path / "launchers.toml"
        launchers_toml.write_text(
            '[launchers.srun]\ntype = "srun"\nuse_slurm_ntasks = true\n'
        )

        profile = load_site_profile(tmp_path)
        assert profile.name == "standard"
        assert profile.resource_style == "standard"
        assert profile.modules == []

    def test_no_files_at_all(self, tmp_path: Path) -> None:
        """Empty directory → STANDARD_SITE."""
        profile = load_site_profile(tmp_path)
        assert profile is STANDARD_SITE

    def test_site_toml_takes_priority(self, tmp_path: Path) -> None:
        """site.toml wins over launchers.toml."""
        (tmp_path / "site.toml").write_text(
            '[site]\nname = "from_site_toml"\nresource_style = "rsc"\n'
        )
        (tmp_path / "launchers.toml").write_text(
            '[launchers.srun]\ntype = "srun"\nresource_style = "standard"\n'
        )

        profile = load_site_profile(tmp_path)
        assert profile.name == "from_site_toml"
        assert profile.resource_style == "rsc"

    def test_setup_commands(self, tmp_path: Path) -> None:
        """setup_commands are loaded from site.toml."""
        (tmp_path / "site.toml").write_text(
            "[site]\n"
            'name = "test"\n'
            'setup_commands = ["ulimit -s unlimited", "export LC_ALL=C"]\n'
        )
        profile = load_site_profile(tmp_path)
        assert profile.setup_commands == ["ulimit -s unlimited", "export LC_ALL=C"]


# ---------------------------------------------------------------------------
# save_site_profile
# ---------------------------------------------------------------------------


class TestSaveSiteProfile:
    """Tests for writing site.toml."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        """Save and reload should produce equivalent profile."""
        original = SiteProfile(
            name="camphor3",
            scheduler="pbs",
            resource_style="rsc",
            modules=["intel/2023.2", "intelmpi/2023.2"],
            simulator_modules={"emses": ["hdf5/1.12"]},
            stdout_format="stdout.%J.log",
            stderr_format="stderr.%J.log",
            extra_sbatch=["--mail-type=END"],
            extra_pbs=["-j oe"],
            pbs_group="testgrp",
            env={"OMP_PROC_BIND": "spread"},
            setup_commands=["ulimit -s unlimited"],
            codex_plugins=[
                CodexPluginRecommendation(
                    name="kudpc-hpc-codex-plugin",
                    display_name="KUDPC HPC",
                    reason="Site workflow guidance.",
                    install_hint="codex plugin add kudpc-hpc-codex-plugin@test",
                    activation_hint="Start a new Codex thread.",
                    visibility="private-or-gated",
                    source="site:camphor3",
                )
            ],
        )
        save_site_profile(tmp_path, original)

        loaded = load_site_profile(tmp_path)
        assert loaded.name == original.name
        assert loaded.scheduler == original.scheduler
        assert loaded.resource_style == original.resource_style
        assert loaded.modules == original.modules
        assert loaded.simulator_modules == original.simulator_modules
        assert loaded.stdout_format == original.stdout_format
        assert loaded.stderr_format == original.stderr_format
        assert loaded.extra_sbatch == original.extra_sbatch
        assert loaded.extra_pbs == original.extra_pbs
        assert loaded.pbs_group == original.pbs_group
        assert loaded.env == original.env
        assert loaded.setup_commands == original.setup_commands
        assert loaded.codex_plugins == original.codex_plugins

    def test_minimal_profile(self, tmp_path: Path) -> None:
        """Saving a minimal profile works."""
        save_site_profile(tmp_path, STANDARD_SITE)
        loaded = load_site_profile(tmp_path)
        assert loaded.name == "standard"
        assert loaded.resource_style == "standard"


# ---------------------------------------------------------------------------
# MOCK_SITE in jobgen
# ---------------------------------------------------------------------------


class TestMockSiteWithJobgen:
    """Verify MOCK_SITE works end-to-end with job script generation."""

    def test_generate_with_mock_site(self, tmp_path: Path) -> None:
        from runops.jobgen.generator import generate_job_script

        run_dir = tmp_path / "R0001"
        run_dir.mkdir()
        (run_dir / "work").mkdir()

        job_config = {"partition": "debug", "walltime": "01:00:00", "ntasks": 4}
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver",
            run_id="R0001",
            site=MOCK_SITE,
            simulator_name="test_sim",
        )
        content = path.read_text()
        assert "module load mock/compiler mock/mpi mock/hdf5" in content
        assert "#SBATCH --ntasks=4" in content  # standard resource style
        assert "#SBATCH --rsc" not in content

    def test_generate_with_rsc_site(self, tmp_path: Path) -> None:
        """Verify a custom rsc site profile works with jobgen."""
        from runops.jobgen.generator import generate_job_script

        camphor = SiteProfile(
            name="camphor3",
            resource_style="rsc",
            modules=["intel/2023.2", "intelmpi/2023.2"],
            simulator_modules={"emses": ["hdf5/1.12"]},
            stdout_format="stdout.%J.log",
            stderr_format="stderr.%J.log",
        )

        run_dir = tmp_path / "R0002"
        run_dir.mkdir()
        (run_dir / "work").mkdir()

        job_config = {
            "partition": "gr10451a",
            "walltime": "120:00:00",
            "ntasks": 800,
            "threads_per_process": 1,
            "cores_per_thread": 1,
        }
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./mpiemses3D plasma.inp",
            run_id="R0002",
            site=camphor,
            simulator_name="emses",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=800:t=1:c=1" in content
        assert "#SBATCH -o stdout.%J.log" in content
        assert "#SBATCH -e stderr.%J.log" in content
        assert "module load intel/2023.2 intelmpi/2023.2 hdf5/1.12" in content
        assert "#SBATCH --ntasks" not in content
