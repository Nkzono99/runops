"""Tests for PBS submission helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from runops.pbs.submit import (
    CommandResult,
    PbsNotFoundError,
    PbsSubmitError,
    parse_job_id,
    qsub_submit,
)


def _make_runner(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> tuple[list[list[str]], callable]:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> CommandResult:
        calls.append(cmd)
        return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)

    return calls, runner


class TestParseJobId:
    """Tests for qsub output parsing."""

    def test_grand_style_job_id(self) -> None:
        assert parse_job_id("12345.grand2\n") == "12345.grand2"

    def test_numeric_job_id(self) -> None:
        assert parse_job_id("12345\n") == "12345"

    def test_empty_output_raises(self) -> None:
        with pytest.raises(PbsSubmitError, match="Could not parse job ID"):
            parse_job_id("")


class TestQsubSubmit:
    """Tests for qsub_submit."""

    def test_success(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "submit" / "job.sh"
        job_sh.parent.mkdir()
        job_sh.write_text("#!/bin/bash -l\n#PBS -q sc\n", encoding="utf-8")

        calls, runner = _make_runner(stdout="12345.grand2\n")
        job_id = qsub_submit(job_sh, tmp_path, runner=runner)

        assert job_id == "12345.grand2"
        assert calls[0][:3] == ["qsub", "-d", str(tmp_path)]
        assert str(job_sh) in calls[0]

    def test_afterok_and_extra_args(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash -l\n", encoding="utf-8")

        calls, runner = _make_runner(stdout="12345\n")
        qsub_submit(
            job_sh,
            tmp_path,
            extra_args=["-q", "sc", "-W", "group_list=testgrp"],
            afterok="11111",
            runner=runner,
        )

        assert "-W" in calls[0]
        assert "depend=afterok:11111" in calls[0]
        assert "-q" in calls[0]
        assert "sc" in calls[0]
        assert "group_list=testgrp" in calls[0]

    def test_nonzero_exit(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash -l\n", encoding="utf-8")

        _, runner = _make_runner(returncode=1, stderr="qsub: Unknown queue")
        with pytest.raises(PbsSubmitError, match="Unknown queue"):
            qsub_submit(job_sh, tmp_path, runner=runner)

    def test_pbs_not_found_propagates(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash -l\n", encoding="utf-8")

        def runner(cmd: list[str]) -> CommandResult:
            raise PbsNotFoundError("qsub not found")

        with pytest.raises(PbsNotFoundError):
            qsub_submit(job_sh, tmp_path, runner=runner)
