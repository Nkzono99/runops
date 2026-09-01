"""FastMCP server factory for runops."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from runops.mcp import tools

Transport = Literal["stdio", "streamable-http"]


def create_mcp_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    stateless_http: bool = True,
    json_response: bool = True,
) -> FastMCP:
    """Create a configured runops FastMCP server."""
    mcp = FastMCP(
        "runops",
        host=host,
        port=port,
        stateless_http=stateless_http,
        json_response=json_response,
    )

    _register_tools(mcp)
    return mcp


def serve(
    *,
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the runops MCP server with the requested transport."""
    server = create_mcp_server(host=host, port=port)
    server.run(transport=transport)


def _register_tools(mcp: FastMCP) -> None:
    """Register all exposed tools on *mcp*."""

    @mcp.tool(
        name="runops.health",
        description="Check the runops MCP server health.",
        structured_output=True,
    )
    def health() -> dict[str, Any]:
        return tools.health()

    @mcp.tool(
        name="runops.provider.info",
        description="Return provider version and contract metadata.",
        structured_output=True,
    )
    def provider_info() -> dict[str, Any]:
        return tools.provider_info()

    @mcp.tool(
        name="runops.capabilities",
        description="Return advertised runops MCP capabilities and safety metadata.",
        structured_output=True,
    )
    def capabilities() -> dict[str, Any]:
        return tools.capabilities()

    @mcp.tool(
        name="runops.project.list",
        description="List the current local runops project.",
        structured_output=True,
    )
    def project_list(project_root: str | None = None) -> dict[str, Any]:
        return tools.project_list(project_root=project_root)

    @mcp.tool(
        name="runops.project.status",
        description="Return a compact project status bundle.",
        structured_output=True,
    )
    def project_status(project_root: str | None = None) -> dict[str, Any]:
        return tools.project_status(project_root=project_root)

    @mcp.tool(
        name="runops.project.inspect",
        description="Return detailed local project metadata and agent context.",
        structured_output=True,
    )
    def project_inspect(project_root: str | None = None) -> dict[str, Any]:
        return tools.project_inspect(project_root=project_root)

    @mcp.tool(
        name="runops.project.plugins",
        description="Return advisory Codex plugin recommendations and metadata checks.",
        structured_output=True,
    )
    def project_plugins(
        project_root: str | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        return tools.project_plugins(project_root=project_root, strict=strict)

    @mcp.tool(
        name="runops.project.doctor",
        description="Diagnose project configuration without mutating files.",
        structured_output=True,
    )
    def project_doctor(project_root: str | None = None) -> dict[str, Any]:
        return tools.project_doctor(project_root=project_root)

    @mcp.tool(
        name="runops.experiment.list",
        description="List bounded Experiment admission units.",
        structured_output=True,
    )
    def experiment_list(
        project_root: str | None = None,
        lifecycle: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return tools.experiment_list(
            project_root=project_root,
            lifecycle=lifecycle,
            limit=limit,
        )

    @mcp.tool(
        name="runops.publication.exports.list",
        description="List paper-facing publication exports without mutating files.",
        structured_output=True,
    )
    def publication_exports_list(
        project_root: str | None = None,
        paper_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return tools.publication_exports_list(
            project_root=project_root,
            paper_id=paper_id,
            limit=limit,
        )

    @mcp.tool(
        name="runops.publication.export.inspect",
        description="Inspect one publication export manifest without mutating files.",
        structured_output=True,
    )
    def publication_export_inspect(
        project_root: str | None = None,
        export: str | None = None,
        paper_id: str | None = None,
        name: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return tools.publication_export_inspect(
            project_root=project_root,
            export=export,
            paper_id=paper_id,
            name=name,
            limit=limit,
        )

    @mcp.tool(
        name="runops.analysis.artifacts",
        description="Inspect run or survey analysis artifact indexes.",
        structured_output=True,
    )
    def analysis_artifacts(
        target: str,
        project_root: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return tools.analysis_artifacts(
            target=target,
            project_root=project_root,
            kind=kind,
            limit=limit,
        )

    @mcp.tool(
        name="runops.survey.summary",
        description="Inspect an existing survey summary aggregate.",
        structured_output=True,
    )
    def survey_summary(
        survey: str,
        project_root: str | None = None,
        include_runs: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        return tools.survey_summary(
            survey=survey,
            project_root=project_root,
            include_runs=include_runs,
            limit=limit,
        )

    @mcp.tool(
        name="runops.survey.plan",
        description="Preview Survey candidates without creating Run directories.",
        structured_output=True,
    )
    def survey_plan(
        survey: str,
        project_root: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        return tools.survey_plan(
            survey=survey,
            project_root=project_root,
            offset=offset,
            limit=limit,
        )

    @mcp.tool(
        name="runops.analysis.plot_columns",
        description="List survey plot columns from an existing summary aggregate.",
        structured_output=True,
    )
    def analysis_plot_columns(
        survey: str,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        return tools.analysis_plot_columns(
            survey=survey,
            project_root=project_root,
        )

    @mcp.tool(
        name="runops.run.list",
        description=(
            "List active run directories by default, with optional archived runs."
        ),
        structured_output=True,
    )
    def run_list(
        project_root: str | None = None,
        status_filter: str | None = None,
        tag: str | None = None,
        experiment_id: str | None = None,
        purpose: str | None = None,
        review_status: str | None = None,
        storage_tier: str | None = None,
        storage_form: str | None = None,
        limit: int = 200,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return tools.run_list(
            project_root=project_root,
            status_filter=status_filter,
            tag=tag,
            experiment_id=experiment_id,
            purpose=purpose,
            review_status=review_status,
            storage_tier=storage_tier,
            storage_form=storage_form,
            limit=limit,
            include_archived=include_archived,
        )

    @mcp.tool(
        name="runops.run.inspect",
        description="Inspect one run manifest and readiness.",
        structured_output=True,
    )
    def run_inspect(run: str, project_root: str | None = None) -> dict[str, Any]:
        return tools.run_inspect(run=run, project_root=project_root)

    @mcp.tool(
        name="runops.run.logs",
        description="Return tail lines from the latest run log.",
        structured_output=True,
    )
    def run_logs(
        run: str,
        project_root: str | None = None,
        lines: int = 50,
        stderr: bool = False,
    ) -> dict[str, Any]:
        return tools.run_logs(
            run=run,
            project_root=project_root,
            lines=lines,
            stderr=stderr,
        )

    @mcp.tool(
        name="runops.slurm.queue",
        description="List Slurm job records known to project manifests.",
        structured_output=True,
    )
    def slurm_queue(
        project_root: str | None = None,
        all_states: bool = False,
        live: bool = False,
    ) -> dict[str, Any]:
        return tools.slurm_queue(
            project_root=project_root,
            all_states=all_states,
            live=live,
        )

    @mcp.tool(
        name="runops.slurm.job.inspect",
        description="Inspect a Slurm job status using squeue/sacct.",
        structured_output=True,
    )
    def slurm_job_inspect(job_id: str) -> dict[str, Any]:
        return tools.slurm_job_inspect(job_id=job_id)

    @mcp.tool(
        name="runops.job.plan_submit",
        description="Plan an sbatch submission command without submitting it.",
        structured_output=True,
    )
    def job_plan_submit(
        run: str,
        project_root: str | None = None,
        queue_name: str | None = None,
        qos: str | None = None,
        afterok: str | None = None,
    ) -> dict[str, Any]:
        return tools.job_plan_submit(
            run=run,
            project_root=project_root,
            queue_name=queue_name,
            qos=qos,
            afterok=afterok,
        )
