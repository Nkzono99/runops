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
        name="runops.project.doctor",
        description="Diagnose project configuration without mutating files.",
        structured_output=True,
    )
    def project_doctor(project_root: str | None = None) -> dict[str, Any]:
        return tools.project_doctor(project_root=project_root)

    @mcp.tool(
        name="runops.run.list",
        description="List run directories and manifest states.",
        structured_output=True,
    )
    def run_list(
        project_root: str | None = None,
        status_filter: str | None = None,
        tag: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return tools.run_list(
            project_root=project_root,
            status_filter=status_filter,
            tag=tag,
            limit=limit,
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
