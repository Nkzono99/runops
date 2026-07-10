"""Tests for Slurm submission module."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from runops.slurm.submit import (
    CommandResult,
    SlurmNotFoundError,
    SlurmSubmissionOutcomeUnknownError,
    SlurmSubmissionRejectedError,
    SlurmSubmitError,
    parse_job_id,
    sbatch_submit,
    submit_command,
)

# ---------------------------------------------------------------------------
# parse_job_id
# ---------------------------------------------------------------------------


class TestParseJobId:
    """Tests for sbatch output parsing."""

    def test_standard_output(self) -> None:
        assert parse_job_id("Submitted batch job 12345\n") == "12345"

    def test_large_job_id(self) -> None:
        assert parse_job_id("Submitted batch job 9999999") == "9999999"

    def test_with_extra_whitespace(self) -> None:
        assert parse_job_id("  Submitted batch job 42  \n") == "42"

    def test_empty_output_raises(self) -> None:
        with pytest.raises(SlurmSubmitError, match="Could not parse job ID"):
            parse_job_id("")

    def test_garbage_output_raises(self) -> None:
        with pytest.raises(SlurmSubmitError, match="Could not parse job ID"):
            parse_job_id("sbatch: error: Batch job submission failed")

    def test_partial_match_raises(self) -> None:
        with pytest.raises(SlurmSubmitError, match="Could not parse job ID"):
            parse_job_id("Submitted batch job")


# ---------------------------------------------------------------------------
# sbatch_submit with mock runner
# ---------------------------------------------------------------------------


def _make_runner(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> tuple[list[list[str]], Callable[[list[str]], CommandResult]]:
    """Create a mock runner that records calls and returns a fixed result."""
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> CommandResult:
        calls.append(cmd)
        return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)

    return calls, runner


class TestSubmitCommand:
    """Tests for executing an already-planned submission vector."""

    def test_executes_exact_vector_and_parses_job_id(self) -> None:
        command = (
            "sbatch",
            "--chdir=/runs/R1/work",
            "--dependency=afterok:123",
            "--partition=debug",
            "--qos=normal",
            "/runs/R1/submit/job.sh",
        )
        calls, runner = _make_runner(stdout="Submitted batch job 67890\n")

        job_id = submit_command(command, runner=runner)

        assert job_id == "67890"
        assert calls == [list(command)]

    @pytest.mark.parametrize("command", [(), ("scancel", "123")])
    def test_rejects_invalid_vector_before_runner(
        self,
        command: tuple[str, ...],
    ) -> None:
        calls, runner = _make_runner(stdout="Submitted batch job 67890\n")

        with pytest.raises(
            SlurmSubmissionRejectedError,
            match="submission command must start with 'sbatch'",
        ):
            submit_command(command, runner=runner)

        assert calls == []

    def test_preserves_runner_failure_format(self) -> None:
        _, runner = _make_runner(
            returncode=2,
            stderr="sbatch: error: invalid account\n",
        )

        with pytest.raises(
            SlurmSubmissionRejectedError,
            match=r"sbatch failed \(exit 2\):\nsbatch: error: invalid account",
        ):
            submit_command(("sbatch", "/runs/R1/submit/job.sh"), runner=runner)

    def test_parses_stdout_through_shared_parser(self) -> None:
        _, runner = _make_runner(stdout="not a job id\n")

        with pytest.raises(
            SlurmSubmissionOutcomeUnknownError,
            match="Could not parse job ID",
        ):
            submit_command(("sbatch", "/runs/R1/submit/job.sh"), runner=runner)

    def test_timeout_is_reported_as_submission_outcome_unknown(self) -> None:
        import subprocess

        with (
            patch(
                "runops.slurm.submit.subprocess.run",
                side_effect=subprocess.TimeoutExpired("sbatch", 60),
            ),
            pytest.raises(
                SlurmSubmissionOutcomeUnknownError,
                match="timed out",
            ),
        ):
            submit_command(("sbatch", "/runs/R1/submit/job.sh"))

    def test_signal_termination_is_reported_as_submission_outcome_unknown(
        self,
    ) -> None:
        _, runner = _make_runner(returncode=-9, stderr="client killed")

        with pytest.raises(
            SlurmSubmissionOutcomeUnknownError,
            match=r"signal 9.*acceptance is unknown",
        ):
            submit_command(("sbatch", "/runs/R1/submit/job.sh"), runner=runner)


class TestSbatchSubmit:
    """Tests for the sbatch_submit function."""

    def test_success(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "submit" / "job.sh"
        job_sh.parent.mkdir()
        job_sh.write_text("#!/bin/bash\necho hello")
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        calls, runner = _make_runner(
            stdout="Submitted batch job 67890\n",
        )
        job_id = sbatch_submit(job_sh, work_dir, runner=runner)

        assert job_id == "67890"
        assert len(calls) == 1
        assert calls[0][0] == "sbatch"
        assert f"--chdir={work_dir}" in calls[0][1]
        assert str(job_sh) in calls[0]

    def test_script_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Job script not found"):
            sbatch_submit(
                tmp_path / "nonexistent.sh",
                tmp_path,
                runner=_make_runner()[1],
            )

    def test_nonzero_exit(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash")

        _, runner = _make_runner(
            returncode=1,
            stderr="sbatch: error: invalid partition\n",
        )
        with pytest.raises(SlurmSubmissionRejectedError, match="invalid partition"):
            sbatch_submit(job_sh, tmp_path, runner=runner)

    def test_unparseable_stdout(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash")

        _, runner = _make_runner(stdout="Unexpected output\n")
        with pytest.raises(
            SlurmSubmissionOutcomeUnknownError,
            match="Could not parse job ID",
        ):
            sbatch_submit(job_sh, tmp_path, runner=runner)

    def test_afterok_dependency(self, tmp_path: Path) -> None:
        """afterok parameter adds --dependency=afterok:<id> to sbatch."""
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash\necho hello")
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        calls, runner = _make_runner(stdout="Submitted batch job 99999\n")
        job_id = sbatch_submit(job_sh, work_dir, afterok="12345", runner=runner)

        assert job_id == "99999"
        assert "--dependency=afterok:12345" in calls[0]

    def test_afterok_with_extra_args(self, tmp_path: Path) -> None:
        """afterok and extra_args both appear in the command."""
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash")
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        calls, runner = _make_runner(stdout="Submitted batch job 11111\n")
        sbatch_submit(
            job_sh,
            work_dir,
            afterok="54321",
            extra_args=["--partition=debug"],
            runner=runner,
        )
        cmd = calls[0]
        assert "--dependency=afterok:54321" in cmd
        assert "--partition=debug" in cmd

    def test_slurm_not_found_propagates(self, tmp_path: Path) -> None:
        job_sh = tmp_path / "job.sh"
        job_sh.write_text("#!/bin/bash")

        def runner(cmd: list[str]) -> CommandResult:
            raise SlurmNotFoundError("sbatch not found")

        with pytest.raises(SlurmNotFoundError):
            sbatch_submit(job_sh, tmp_path, runner=runner)

    def test_delegates_constructed_tuple_to_submit_command(
        self,
        tmp_path: Path,
    ) -> None:
        job_sh = tmp_path / "submit" / "job.sh"
        job_sh.parent.mkdir()
        job_sh.write_text("#!/bin/bash\n#SBATCH --job-name=test\n")
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        _, runner = _make_runner()
        expected = (
            "sbatch",
            f"--chdir={work_dir}",
            "--dependency=afterok:12345",
            "--partition=debug",
            "--qos=normal",
            str(job_sh),
        )

        with patch(
            "runops.slurm.submit.submit_command",
            return_value="24680",
        ) as submit:
            job_id = sbatch_submit(
                job_sh,
                work_dir,
                extra_args=["--partition=debug", "--qos=normal"],
                afterok="12345",
                runner=runner,
            )

        assert job_id == "24680"
        submit.assert_called_once_with(expected, runner=runner)
