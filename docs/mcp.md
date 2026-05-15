# runops MCP Provider

runops は Ops MCP Contract v0.1 に沿った MCP provider を持つ。
MCP は runops の domain model ではなく、既存の CLI / Python API を
AI host から安全に呼ぶための edge interface として扱う。

## 入口

```bash
# local stdio provider
runo mcp serve --transport stdio

# local Streamable HTTP provider
runo mcp serve --transport streamable-http --host 127.0.0.1 --port 18765

# registry / conformance helpers
runo mcp check
runo mcp tools --json
runo mcp resources --json
runo mcp prompts --json
```

`runops` alias でも同じ command surface を使える。
stdio transport では stdout に MCP JSON-RPC だけを流す。通常の diagnostic は
stderr に出す。

HTTP transport は既定で localhost に bind する。`0.0.0.0` などに bind するには
明示的に `--allow-remote` が必要。remote / shared service として公開する場合は、
host 側の bearer token や tunnel policy と合わせて使う。

## Safety Posture

初期実装では read / inspect / plan tool だけを expose する。
write / external / destructive tool は registry 上に disabled metadata として残すが、
デフォルトでは MCP tool として公開しない。

| Safety class | Level | 初期公開 | 例 |
|--------------|------:|----------|----|
| `read` | 0 | yes | `runops.project.status`, `runops.run.list` |
| `inspect` | 1 | yes | `runops.run.inspect`, `runops.run.logs` |
| `plan` | 2 | yes | `runops.job.plan_submit` |
| `write` | 3 | no | local file mutation |
| `external` | 4 | no | Slurm `sbatch` |
| `destructive` | 5 | no | `scancel`, run deletion |

`runops.job.submit`, `runops.job.cancel`, `runops.run.delete` は disabled by default。
将来 expose する場合も、`confirm=true`、`dry_run=false`、server policy enable、
audit record を必須にする。

## Result Envelope

すべての tool は `structuredContent` に Ops MCP envelope を返す。
主要フィールドは以下。

```json
{
  "contract_version": "0.1",
  "provider": "runops",
  "provider_version": "0.9.0",
  "tool": "runops.project.status",
  "operation_id": "op_...",
  "status": "ok",
  "safety": {
    "level": 0,
    "class": "read",
    "side_effects": false
  },
  "project": {
    "id": "demo-project",
    "kind": "experiment",
    "root": "/path/to/project",
    "location": "local"
  },
  "summary": "1 run(s); project status is ok.",
  "data": {},
  "warnings": [],
  "errors": [],
  "next_actions": [],
  "resources": [],
  "audit": {
    "started_at": "2026-05-12T10:00:00+09:00",
    "completed_at": "2026-05-12T10:00:01+09:00",
    "duration_ms": 1000
  }
}
```

error / blocked も JSON-RPC protocol error ではなく、通常の tool result envelope として
返す。protocol request 自体が壊れている場合だけ JSON-RPC error になる。

## Exposed Tools

### Common provider tools

| Tool | Safety | 内容 |
|------|--------|------|
| `runops.health` | read | MCP server health |
| `runops.provider.info` | read | provider / contract / transport metadata |
| `runops.capabilities` | read | tool registry と safety metadata |
| `runops.project.list` | read | server cwd から発見できる local project |
| `runops.project.status` | read | compact project status |
| `runops.project.inspect` | inspect | `runo context` 相当の詳細 context |
| `runops.project.doctor` | read | project diagnostics。環境保存などの mutation はしない |

### run / Slurm tools

| Tool | Safety | 内容 |
|------|--------|------|
| `runops.run.list` | read | manifest を読んで run 一覧を返す |
| `runops.run.inspect` | inspect | run manifest と readiness を返す |
| `runops.run.logs` | inspect | 最新 stdout/stderr log の tail を返す |
| `runops.slurm.queue` | inspect | manifest に記録された job 情報を一覧する |
| `runops.slurm.job.inspect` | inspect | `squeue` / `sacct` で job state を読む |
| `runops.job.plan_submit` | plan | `sbatch` command と precondition を返す。submit はしない |

`runops.slurm.queue(live=true)` と `runops.slurm.job.inspect` は Slurm command を読むため、
Slurm が PATH にない環境では blocked envelope を返すことがある。

### analysis / publication tools

| Tool | Safety | 内容 |
|------|--------|------|
| `runops.analysis.artifacts` | inspect | run の `analysis/artifacts.toml` または survey の `summary/artifacts.toml` を読む |
| `runops.survey.summary` | inspect | 既存 `summary/survey_summary.json` の counts / stats / readiness を読む |
| `runops.analysis.plot_columns` | inspect | 既存 `survey_summary.json` から plot 可能な列を返す |
| `runops.publication.exports.list` | read | `exports/papers/` 配下の publication export manifest を列挙する |
| `runops.publication.export.inspect` | inspect | 1 つの publication export `manifest.json` と files/source metadata を読む |

これらは read / inspect 専用で、`runo analyze collect`, `plot`, `export` のような
成果物生成は行わない。missing / 壊れた artifact index や manifest は MCP protocol
error ではなく、warning / error を含む envelope として返す。

### paper request tools

| Tool | Safety | 内容 |
|------|--------|------|
| `runops.paper.requests.list` | read | `research/paper_requests.toml` の paper-facing request を列挙する |
| `runops.paper.request.draft` | plan | paper-facing request 候補を検証し、追記用 TOML snippet と保存先を返す |
| `runops.paper.request.plan` | plan | 1 件の request を `research/agenda.md` / `research/proposals/` へ戻す plan を返す |

paper request は paper draft から runops project に戻る追加解析・図表・追加実験・export
要望の contract であり、実行キューではない。`experiment_request` も MCP 経由では
submit せず、case / survey design と human gate を含む plan に留める。
paperops など外部の paper tool は `runops.paper.request.draft` で enum、id 形式、
重複、保存先を preview してから、人間の確認後に snippet を
`research/paper_requests.toml` へ追記する。
duplicate id は append 可能な warning ではなく validation error として扱い、
`toml_snippet` と append next action は返さず、`suggested_request_id` を返す。

## Submit Planning

`runops.job.plan_submit` は `runo runs submit --dry-run` 相当の structured plan を返す。
確認する precondition は主に以下。

- manifest status が `created`
- `submit/job.sh` が存在する
- `job.sh` に `#SBATCH` directive がある
- `input/` が存在し、空ではない

戻り値の `data.command` は実行予定の argument array であり、shell interpolation を含まない。
例:

```json
{
  "command": [
    "sbatch",
    "--chdir=/project/runs/demo/R20260512-0001/work",
    "--partition=debug",
    "--qos=normal",
    "/project/runs/demo/R20260512-0001/submit/job.sh"
  ],
  "dry_run": true,
  "will_submit": true
}
```

## Codex / Host Config Example

local stdio:

```toml
[mcp_servers.runops]
command = "runo"
args = ["mcp", "serve", "--transport", "stdio"]
startup_timeout_sec = 20
tool_timeout_sec = 180
enabled = true
required = false
enabled_tools = [
  "runops.health",
  "runops.provider.info",
  "runops.capabilities",
  "runops.project.list",
  "runops.project.status",
  "runops.project.inspect",
  "runops.project.doctor",
  "runops.publication.exports.list",
  "runops.publication.export.inspect",
  "runops.analysis.artifacts",
  "runops.survey.summary",
  "runops.analysis.plot_columns",
  "runops.paper.requests.list",
  "runops.paper.request.draft",
  "runops.paper.request.plan",
  "runops.run.list",
  "runops.run.inspect",
  "runops.run.logs",
  "runops.slurm.queue",
  "runops.slurm.job.inspect",
  "runops.job.plan_submit"
]
disabled_tools = [
  "runops.job.submit",
  "runops.job.cancel",
  "runops.run.delete"
]
```

HPC login node over SSH tunnel:

```bash
# on login node
runo mcp serve --transport streamable-http --host 127.0.0.1 --port 18765

# on local machine
ssh -N -L 18765:127.0.0.1:18765 hpc-login
```

```toml
[mcp_servers.runops_hpc]
url = "http://127.0.0.1:18765/mcp"
startup_timeout_sec = 20
tool_timeout_sec = 180
enabled = true
required = false
```

## Implementation Notes

実装は `src/runops/mcp/` に閉じ込める。

| File | 役割 |
|------|------|
| `server.py` | FastMCP server factory / tool registration |
| `tools.py` | domain API を呼ぶ read / inspect / plan tool 実装 |
| `schemas.py` | Ops MCP envelope / audit helper |
| `safety.py` | safety metadata |
| `registry.py` | tool registry / conformance check |

CLI は `src/runops/cli/mcp.py` で薄く接続する。
domain logic は MCP layer に隠し実装せず、`core.context`, `core.discovery`,
`core.manifest`, `slurm.query` など既存の deterministic API を使う。

Agent-facing action との対応は `core/actions/specs.py` の `ActionSpec.mcp_tools`
に記録する。`runo mcp check` と registry conformance test は、ActionSpec が参照する
MCP tool が登録済みであること、unsafe な action tool が確認 metadata を持つことを
検査する。
