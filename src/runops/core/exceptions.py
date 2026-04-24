"""Domain-specific exceptions for runops core logic."""

from __future__ import annotations

from collections.abc import Sequence


class SimctlError(Exception):
    """Base exception for all runops domain errors."""


class ProjectNotFoundError(SimctlError):
    """Raised when runops.toml cannot be found in any parent directory."""


class ProjectConfigError(SimctlError):
    """Raised when runops.toml is invalid or missing required fields."""


class CaseNotFoundError(SimctlError):
    """Raised when a case directory or case.toml cannot be found."""


class CaseConfigError(SimctlError):
    """Raised when case.toml is invalid or missing required fields."""


class SurveyConfigError(SimctlError):
    """Raised when survey.toml is invalid or missing required fields."""


class ManifestNotFoundError(SimctlError):
    """Raised when manifest.toml cannot be found in a run directory."""


class ManifestError(SimctlError):
    """Raised when manifest.toml is invalid or cannot be written."""


class InvalidStateTransitionError(SimctlError):
    """Raised when an invalid state transition is attempted.

    Attributes:
        current: The current state.
        target: The attempted target state.
    """

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid state transition: {current!r} -> {target!r}")


class DuplicateRunIdError(SimctlError):
    """Raised when a duplicate run_id is detected within a project.

    Attributes:
        run_id: The duplicate run_id.
        paths: List of paths where the duplicate was found.
    """

    def __init__(self, run_id: str, paths: list[str]) -> None:
        self.run_id = run_id
        self.paths = paths
        super().__init__(f"Duplicate run_id {run_id!r} found at: {', '.join(paths)}")


class RunNotFoundError(SimctlError):
    """Raised when a run cannot be found by run_id or path."""


class ProvenanceError(SimctlError):
    """Raised when provenance information cannot be collected."""


class KnowledgeSourceError(SimctlError):
    """Raised when a knowledge source operation fails.

    Covers sync failures, validation errors, and configuration issues.
    """


class SessionImportError(SimctlError):
    """Raised when a Codex session log cannot be imported."""


class DemoReplayError(SimctlError):
    """Raised when a demo replay UI cannot be built."""


class ParameterValidationError(SimctlError):
    """Raised when parameter validation finds errors.

    Attributes:
        issues: List of ValidationIssue instances.
    """

    def __init__(self, issues: Sequence[object]) -> None:
        self.issues = issues
        error_count = sum(1 for i in issues if getattr(i, "severity", "") == "error")
        super().__init__(f"Parameter validation failed with {error_count} error(s)")
