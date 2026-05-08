"""Tests for core survey module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from runops.core.exceptions import SurveyConfigError
from runops.core.survey import (
    expand_axes,
    expand_survey,
    generate_display_name,
    load_survey,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestLoadSurvey:
    """Tests for load_survey()."""

    def test_load_sample_survey(self, tmp_path: Path) -> None:
        shutil.copy(FIXTURES_DIR / "sample_survey.toml", tmp_path / "survey.toml")
        survey = load_survey(tmp_path)
        assert survey.id == "S20260327-cavity-u-a"
        assert survey.name == "u-aspect scan"
        assert survey.base_case == "cavity_base"
        assert survey.simulator == "lunar_pic"
        assert survey.launcher == "slurm_srun"
        assert survey.classification.model == "cavity"
        assert survey.classification.tags == ["scan", "paper1"]
        assert len(survey.axes) == 3
        assert survey.axes["u"] == [2.0e5, 4.0e5, 8.0e5]
        assert survey.naming_template == "u{u}_a{aspect}_s{seed}"
        assert survey.job.partition == "gr20001a"

    def test_missing_survey_toml(self, tmp_path: Path) -> None:
        with pytest.raises(SurveyConfigError, match=r"survey\.toml not found"):
            load_survey(tmp_path)

    def test_missing_survey_section(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text("[axes]\nu = [1, 2]\n")
        with pytest.raises(SurveyConfigError, match="\\[survey\\] section"):
            load_survey(tmp_path)

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nbase_case = "c"\nsimulator = "s"\n'
        )
        with pytest.raises(SurveyConfigError, match=r"survey\.launcher"):
            load_survey(tmp_path)

    def test_empty_axis(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nname = "t"\nbase_case = "c"\n'
            'simulator = "s"\nlauncher = "l"\n\n'
            "[axes]\nu = []\n"
        )
        with pytest.raises(SurveyConfigError, match="must not be empty"):
            load_survey(tmp_path)

    def test_invalid_toml(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text("bad toml [[[")
        with pytest.raises(SurveyConfigError, match="Invalid TOML"):
            load_survey(tmp_path)

    def test_load_survey_with_linked(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nname = "t"\nbase_case = "c"\n'
            'simulator = "s"\nlauncher = "l"\n\n'
            "[axes]\nseed = [1, 2]\n\n"
            "[[linked]]\nnx = [32, 64]\nny = [32, 64]\n"
        )
        survey = load_survey(tmp_path)
        assert len(survey.linked) == 1
        assert survey.linked[0]["nx"] == [32, 64]
        assert survey.linked[0]["ny"] == [32, 64]

    def test_linked_mismatched_lengths(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nname = "t"\nbase_case = "c"\n'
            'simulator = "s"\nlauncher = "l"\n\n'
            "[[linked]]\nnx = [32, 64, 128]\nny = [32, 64]\n"
        )
        with pytest.raises(SurveyConfigError, match="same number of values"):
            load_survey(tmp_path)

    def test_linked_empty_parameter(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nname = "t"\nbase_case = "c"\n'
            'simulator = "s"\nlauncher = "l"\n\n'
            "[[linked]]\nnx = []\n"
        )
        with pytest.raises(SurveyConfigError, match="must not be empty"):
            load_survey(tmp_path)

    def test_linked_overlaps_with_axes(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nname = "t"\nbase_case = "c"\n'
            'simulator = "s"\nlauncher = "l"\n\n'
            "[axes]\nnx = [32, 64]\n\n"
            "[[linked]]\nnx = [32, 64]\nny = [32, 64]\n"
        )
        with pytest.raises(SurveyConfigError, match="appear in both"):
            load_survey(tmp_path)

    def test_linked_duplicate_across_groups(self, tmp_path: Path) -> None:
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nname = "t"\nbase_case = "c"\n'
            'simulator = "s"\nlauncher = "l"\n\n'
            "[[linked]]\nnx = [32, 64]\nny = [32, 64]\n\n"
            "[[linked]]\nnx = [128, 256]\ndt = [0.1, 0.01]\n"
        )
        with pytest.raises(SurveyConfigError, match="multiple"):
            load_survey(tmp_path)

    def test_linked_single_table_error(self, tmp_path: Path) -> None:
        """[linked] (single table) should be rejected; must use [[linked]]."""
        (tmp_path / "survey.toml").write_text(
            '[survey]\nid = "S1"\nname = "t"\nbase_case = "c"\n'
            'simulator = "s"\nlauncher = "l"\n\n'
            "[linked]\nnx = [32, 64]\n"
        )
        with pytest.raises(SurveyConfigError, match="array of tables"):
            load_survey(tmp_path)


class TestExpandAxes:
    """Tests for expand_axes()."""

    def test_single_axis(self) -> None:
        result = expand_axes({"x": [1, 2, 3]})
        assert result == [{"x": 1}, {"x": 2}, {"x": 3}]

    def test_two_axes(self) -> None:
        result = expand_axes({"a": [1, 2], "b": [10, 20]})
        assert len(result) == 4
        assert {"a": 1, "b": 10} in result
        assert {"a": 2, "b": 20} in result

    def test_three_axes(self) -> None:
        result = expand_axes(
            {
                "u": [2e5, 4e5],
                "aspect": [2.0, 4.0],
                "seed": [1, 2],
            }
        )
        assert len(result) == 8

    def test_empty_axes(self) -> None:
        assert expand_axes({}) == []

    def test_preserves_order(self) -> None:
        result = expand_axes({"a": [1, 2], "b": [10, 20]})
        # Cartesian product order
        assert result[0] == {"a": 1, "b": 10}
        assert result[1] == {"a": 1, "b": 20}
        assert result[2] == {"a": 2, "b": 10}
        assert result[3] == {"a": 2, "b": 20}


class TestExpandSurvey:
    """Tests for expand_survey()."""

    def test_axes_only(self) -> None:
        result = expand_survey({"a": [1, 2], "b": [10, 20]}, [])
        assert len(result) == 4
        assert {"a": 1, "b": 10} in result

    def test_linked_only(self) -> None:
        result = expand_survey({}, [{"nx": [32, 64], "ny": [32, 64]}])
        assert len(result) == 2
        assert result[0] == {"nx": 32, "ny": 32}
        assert result[1] == {"nx": 64, "ny": 64}

    def test_axes_and_linked(self) -> None:
        result = expand_survey(
            {"seed": [1, 2]},
            [{"nx": [32, 64], "ny": [32, 64]}],
        )
        assert len(result) == 4  # 2 seeds x 2 linked pairs
        assert {"seed": 1, "nx": 32, "ny": 32} in result
        assert {"seed": 1, "nx": 64, "ny": 64} in result
        assert {"seed": 2, "nx": 32, "ny": 32} in result
        assert {"seed": 2, "nx": 64, "ny": 64} in result

    def test_multiple_linked_groups(self) -> None:
        result = expand_survey(
            {},
            [
                {"nx": [32, 64], "ny": [32, 64]},
                {"dt": [0.1, 0.01], "steps": [100, 1000]},
            ],
        )
        # 2 pairs x 2 pairs = 4 (Cartesian across groups)
        assert len(result) == 4
        assert {"nx": 32, "ny": 32, "dt": 0.1, "steps": 100} in result
        assert {"nx": 64, "ny": 64, "dt": 0.01, "steps": 1000} in result

    def test_axes_and_multiple_linked_groups(self) -> None:
        result = expand_survey(
            {"seed": [1, 2, 3]},
            [
                {"nx": [32, 64], "ny": [32, 64]},
                {"dt": [0.1, 0.01]},
            ],
        )
        # 3 seeds x 2 linked pairs x 2 dt values = 12
        assert len(result) == 12

    def test_both_empty(self) -> None:
        assert expand_survey({}, []) == []

    def test_preserves_linked_order(self) -> None:
        result = expand_survey(
            {"seed": [1]},
            [{"nx": [32, 64, 128], "ny": [32, 64, 128]}],
        )
        assert len(result) == 3
        assert result[0] == {"seed": 1, "nx": 32, "ny": 32}
        assert result[1] == {"seed": 1, "nx": 64, "ny": 64}
        assert result[2] == {"seed": 1, "nx": 128, "ny": 128}


class TestGenerateDisplayName:
    """Tests for generate_display_name()."""

    def test_basic_template(self) -> None:
        result = generate_display_name(
            "u{u}_a{aspect}_s{seed}",
            {"u": 4e5, "aspect": 4.0, "seed": 3},
        )
        assert result == "u400000_a4_s3"

    def test_empty_template(self) -> None:
        assert generate_display_name("", {"a": 1}) == ""

    def test_integer_values(self) -> None:
        result = generate_display_name("nx{nx}", {"nx": 256})
        assert result == "nx256"

    def test_string_values(self) -> None:
        result = generate_display_name("mode_{mode}", {"mode": "fast"})
        assert result == "mode_fast"
