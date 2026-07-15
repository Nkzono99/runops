"""Compatibility facade for runops MCP tool implementations."""

from __future__ import annotations

from runops.mcp._tools.analysis import (
    analysis_artifacts,
    analysis_plot_columns,
    survey_summary,
)
from runops.mcp._tools.project import (
    project_doctor,
    project_inspect,
    project_list,
    project_plugins,
    project_status,
)
from runops.mcp._tools.provider import capabilities, health, provider_info
from runops.mcp._tools.publication import (
    publication_export_inspect,
    publication_exports_list,
)
from runops.mcp._tools.runs import run_inspect, run_list, run_logs
from runops.mcp._tools.scheduler import (
    job_plan_submit,
    slurm_job_inspect,
    slurm_queue,
)

__all__ = [
    "analysis_artifacts",
    "analysis_plot_columns",
    "capabilities",
    "health",
    "job_plan_submit",
    "project_doctor",
    "project_inspect",
    "project_list",
    "project_plugins",
    "project_status",
    "provider_info",
    "publication_export_inspect",
    "publication_exports_list",
    "run_inspect",
    "run_list",
    "run_logs",
    "slurm_job_inspect",
    "slurm_queue",
    "survey_summary",
]
