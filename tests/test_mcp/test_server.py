"""Tests for the runops FastMCP server wiring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runops.mcp import server as mcp_server
from runops.mcp.registry import exposed_tool_specs


class _FakeMCP:
    """Small registrar with the FastMCP ``tool`` decorator shape."""

    def __init__(
        self,
        name: str = "runops",
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.kwargs = kwargs
        self.tools: dict[str, dict[str, Any]] = {}

    def tool(
        self,
        *,
        name: str,
        description: str,
        structured_output: bool,
    ) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
        def decorator(
            fn: Callable[..., dict[str, Any]],
        ) -> Callable[..., dict[str, Any]]:
            self.tools[name] = {
                "description": description,
                "structured_output": structured_output,
                "callback": fn,
            }
            return fn

        return decorator


_TOOL_ATTRS = {
    "runops.health": "health",
    "runops.provider.info": "provider_info",
    "runops.capabilities": "capabilities",
    "runops.project.list": "project_list",
    "runops.project.status": "project_status",
    "runops.project.inspect": "project_inspect",
    "runops.project.doctor": "project_doctor",
    "runops.publication.exports.list": "publication_exports_list",
    "runops.publication.export.inspect": "publication_export_inspect",
    "runops.analysis.artifacts": "analysis_artifacts",
    "runops.survey.summary": "survey_summary",
    "runops.analysis.plot_columns": "analysis_plot_columns",
    "runops.paper.requests.list": "paper_requests_list",
    "runops.paper.request.plan": "paper_request_plan",
    "runops.run.list": "run_list",
    "runops.run.inspect": "run_inspect",
    "runops.run.logs": "run_logs",
    "runops.slurm.queue": "slurm_queue",
    "runops.slurm.job.inspect": "slurm_job_inspect",
    "runops.job.plan_submit": "job_plan_submit",
}


def test_register_tools_matches_exposed_registry() -> None:
    fake = _FakeMCP()

    mcp_server._register_tools(fake)

    assert set(fake.tools) == {spec.name for spec in exposed_tool_specs()}
    assert all(tool["structured_output"] is True for tool in fake.tools.values())


def test_registered_tool_wrappers_delegate_to_domain_tools(
    monkeypatch: Any,
) -> None:
    calls: dict[str, dict[str, Any]] = {}

    def make_stub(tool_name: str) -> Callable[..., dict[str, Any]]:
        def stub(**kwargs: Any) -> dict[str, Any]:
            calls[tool_name] = kwargs
            return {"stub": tool_name, "kwargs": kwargs}

        return stub

    for tool_name, attr_name in _TOOL_ATTRS.items():
        monkeypatch.setattr(mcp_server.tools, attr_name, make_stub(tool_name))

    fake = _FakeMCP()
    mcp_server._register_tools(fake)

    assert fake.tools["runops.health"]["callback"]() == {
        "stub": "runops.health",
        "kwargs": {},
    }
    assert fake.tools["runops.project.list"]["callback"](project_root="root") == {
        "stub": "runops.project.list",
        "kwargs": {"project_root": "root"},
    }
    assert fake.tools["runops.publication.exports.list"]["callback"](
        project_root="root",
        paper_id="draft-a",
        limit=5,
    ) == {
        "stub": "runops.publication.exports.list",
        "kwargs": {"project_root": "root", "paper_id": "draft-a", "limit": 5},
    }
    assert fake.tools["runops.publication.export.inspect"]["callback"](
        project_root="root",
        export="draft-a/fig2",
        limit=10,
    ) == {
        "stub": "runops.publication.export.inspect",
        "kwargs": {
            "project_root": "root",
            "export": "draft-a/fig2",
            "paper_id": None,
            "name": None,
            "limit": 10,
        },
    }
    assert fake.tools["runops.analysis.artifacts"]["callback"](
        "R20260512-0001",
        project_root="root",
        kind="figure",
        limit=2,
    ) == {
        "stub": "runops.analysis.artifacts",
        "kwargs": {
            "target": "R20260512-0001",
            "project_root": "root",
            "kind": "figure",
            "limit": 2,
        },
    }
    assert fake.tools["runops.survey.summary"]["callback"](
        "runs/survey-a",
        project_root="root",
        include_runs=True,
        limit=2,
    ) == {
        "stub": "runops.survey.summary",
        "kwargs": {
            "survey": "runs/survey-a",
            "project_root": "root",
            "include_runs": True,
            "limit": 2,
        },
    }
    assert fake.tools["runops.analysis.plot_columns"]["callback"](
        "runs/survey-a",
        project_root="root",
    ) == {
        "stub": "runops.analysis.plot_columns",
        "kwargs": {"survey": "runs/survey-a", "project_root": "root"},
    }
    assert fake.tools["runops.paper.requests.list"]["callback"](
        project_root="root",
        paper_id="draft-a",
        status_filter="open",
        limit=2,
    ) == {
        "stub": "runops.paper.requests.list",
        "kwargs": {
            "project_root": "root",
            "paper_id": "draft-a",
            "status_filter": "open",
            "limit": 2,
        },
    }
    assert fake.tools["runops.paper.request.plan"]["callback"](
        "REQ-001",
        project_root="root",
    ) == {
        "stub": "runops.paper.request.plan",
        "kwargs": {"request_id": "REQ-001", "project_root": "root"},
    }
    assert fake.tools["runops.run.list"]["callback"](
        project_root="root",
        status_filter="created",
        tag="smoke",
        limit=3,
    ) == {
        "stub": "runops.run.list",
        "kwargs": {
            "project_root": "root",
            "status_filter": "created",
            "tag": "smoke",
            "limit": 3,
        },
    }
    assert fake.tools["runops.run.inspect"]["callback"](
        "R20260512-0001",
        project_root="root",
    ) == {
        "stub": "runops.run.inspect",
        "kwargs": {"run": "R20260512-0001", "project_root": "root"},
    }
    assert fake.tools["runops.run.logs"]["callback"](
        "R20260512-0001",
        project_root="root",
        lines=2,
        stderr=True,
    ) == {
        "stub": "runops.run.logs",
        "kwargs": {
            "run": "R20260512-0001",
            "project_root": "root",
            "lines": 2,
            "stderr": True,
        },
    }
    assert fake.tools["runops.slurm.queue"]["callback"](
        project_root="root",
        all_states=True,
        live=True,
    ) == {
        "stub": "runops.slurm.queue",
        "kwargs": {"project_root": "root", "all_states": True, "live": True},
    }
    assert fake.tools["runops.slurm.job.inspect"]["callback"]("12345") == {
        "stub": "runops.slurm.job.inspect",
        "kwargs": {"job_id": "12345"},
    }
    assert fake.tools["runops.job.plan_submit"]["callback"](
        "R20260512-0001",
        project_root="root",
        queue_name="debug",
        qos="normal",
        afterok="111",
    ) == {
        "stub": "runops.job.plan_submit",
        "kwargs": {
            "run": "R20260512-0001",
            "project_root": "root",
            "queue_name": "debug",
            "qos": "normal",
            "afterok": "111",
        },
    }

    assert set(calls) >= {
        "runops.health",
        "runops.analysis.artifacts",
        "runops.analysis.plot_columns",
        "runops.paper.request.plan",
        "runops.paper.requests.list",
        "runops.project.list",
        "runops.publication.export.inspect",
        "runops.publication.exports.list",
        "runops.run.list",
        "runops.run.inspect",
        "runops.run.logs",
        "runops.survey.summary",
        "runops.slurm.queue",
        "runops.slurm.job.inspect",
        "runops.job.plan_submit",
    }


def test_create_mcp_server_configures_fastmcp(
    monkeypatch: Any,
) -> None:
    created: list[_FakeMCP] = []

    class FakeFastMCP(_FakeMCP):
        def __init__(self, name: str, **kwargs: Any) -> None:
            super().__init__(name, **kwargs)
            created.append(self)

    monkeypatch.setattr(mcp_server, "FastMCP", FakeFastMCP)

    server = mcp_server.create_mcp_server(
        host="127.0.0.2",
        port=18765,
        stateless_http=False,
        json_response=False,
    )

    assert server is created[0]
    assert server.name == "runops"
    assert server.kwargs == {
        "host": "127.0.0.2",
        "port": 18765,
        "stateless_http": False,
        "json_response": False,
    }
    assert set(server.tools) == {spec.name for spec in exposed_tool_specs()}


def test_serve_runs_requested_transport(monkeypatch: Any) -> None:
    calls: dict[str, Any] = {}

    class FakeServer:
        def run(self, *, transport: str) -> None:
            calls["transport"] = transport

    def fake_create_mcp_server(*, host: str, port: int) -> FakeServer:
        calls["host"] = host
        calls["port"] = port
        return FakeServer()

    monkeypatch.setattr(mcp_server, "create_mcp_server", fake_create_mcp_server)

    mcp_server.serve(transport="streamable-http", host="127.0.0.1", port=18765)

    assert calls == {
        "host": "127.0.0.1",
        "port": 18765,
        "transport": "streamable-http",
    }
