"""Tests for core case module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from runops.core.case import load_case, parse_walltime_hours, resolve_case
from runops.core.exceptions import CaseConfigError, CaseNotFoundError

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestLoadCase:
    """Tests for load_case()."""

    def test_load_sample_case(self, tmp_path: Path) -> None:
        shutil.copy(FIXTURES_DIR / "sample_case.toml", tmp_path / "case.toml")
        case = load_case(tmp_path)
        assert case.name == "cavity_base"
        assert case.simulator == "lunar_pic"
        assert case.launcher == "slurm_srun"
        assert case.description == "baseline cavity model"
        assert case.classification.model == "cavity"
        assert case.classification.submodel == "rectangular"
        assert case.classification.tags == ["baseline"]
        assert case.job.partition == "gr20001a"
        assert case.job.nodes == 1
        assert case.job.ntasks == 32
        assert case.job.walltime == "12:00:00"
        assert case.params["nx"] == 256
        assert case.params["dt"] == 1.0e-8

    def test_missing_case_toml(self, tmp_path: Path) -> None:
        with pytest.raises(CaseNotFoundError, match=r"case\.toml not found"):
            load_case(tmp_path)

    def test_missing_case_section(self, tmp_path: Path) -> None:
        (tmp_path / "case.toml").write_text("[params]\nx = 1\n")
        with pytest.raises(CaseConfigError, match="\\[case\\] section"):
            load_case(tmp_path)

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        (tmp_path / "case.toml").write_text('[case]\nname = "test"\nsimulator = "s"\n')
        with pytest.raises(CaseConfigError, match=r"case\.launcher"):
            load_case(tmp_path)

    def test_invalid_toml(self, tmp_path: Path) -> None:
        (tmp_path / "case.toml").write_text("invalid [[[")
        with pytest.raises(CaseConfigError, match="Invalid TOML"):
            load_case(tmp_path)

    def test_frozen_dataclass(self, tmp_path: Path) -> None:
        shutil.copy(FIXTURES_DIR / "sample_case.toml", tmp_path / "case.toml")
        case = load_case(tmp_path)
        with pytest.raises(AttributeError):
            case.name = "other"  # type: ignore[misc]

    def test_empty_params(self, tmp_path: Path) -> None:
        (tmp_path / "case.toml").write_text(
            '[case]\nname = "t"\nsimulator = "s"\nlauncher = "l"\n'
        )
        case = load_case(tmp_path)
        assert case.params == {}

    @pytest.mark.parametrize(
        "walltime",
        [
            "",
            "-01:00:00",
            "00:00:00",
            "01:60:00",
            "01:00:60",
            "1:00",
        ],
    )
    def test_rejects_invalid_or_non_positive_walltime(
        self,
        tmp_path: Path,
        walltime: str,
    ) -> None:
        (tmp_path / "case.toml").write_text(
            "[case]\n"
            'name = "test"\n'
            'simulator = "sim"\n'
            'launcher = "srun"\n\n'
            "[job]\n"
            f'walltime = "{walltime}"\n',
            encoding="utf-8",
        )

        with pytest.raises(CaseConfigError, match="Invalid walltime"):
            load_case(tmp_path)


@pytest.mark.parametrize(
    ("walltime", "expected_hours"),
    [
        ("0:00:01", 1 / 3600),
        ("12:34:56", 12 + 34 / 60 + 56 / 3600),
        ("120:00:00", 120.0),
        ("5-00:00:00", 120.0),
    ],
)
def test_parse_walltime_hours_preserves_supported_formats(
    walltime: str,
    expected_hours: float,
) -> None:
    assert parse_walltime_hours(walltime) == pytest.approx(expected_hours)


class TestResolveCase:
    """Tests for resolve_case()."""

    def test_resolve_existing_case(self, tmp_path: Path) -> None:
        case_dir = tmp_path / "cases" / "my_case"
        case_dir.mkdir(parents=True)
        (case_dir / "case.toml").write_text(
            '[case]\nname = "my_case"\nsimulator = "s"\nlauncher = "l"\n'
        )
        result = resolve_case("my_case", tmp_path)
        assert result == case_dir

    def test_resolve_nonexistent_case(self, tmp_path: Path) -> None:
        (tmp_path / "cases").mkdir()
        with pytest.raises(CaseNotFoundError, match="not found"):
            resolve_case("nonexistent", tmp_path)

    def test_resolve_dir_without_case_toml(self, tmp_path: Path) -> None:
        case_dir = tmp_path / "cases" / "empty_case"
        case_dir.mkdir(parents=True)
        with pytest.raises(CaseNotFoundError, match=r"not found"):
            resolve_case("empty_case", tmp_path)
