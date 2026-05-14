# Paper Request Contract

paper draft から runops project へ戻す追加解析・図表・追加実験の要望は、
`research/paper_requests.toml` に structured queue として置く。
これは実行キューではなく、`research/agenda.md` や `research/proposals/` へ
判断を戻すための handoff である。

## File

```toml
#:schema https://runops.dev/schemas/paper_requests.json
schema_version = 1

[[requests]]
id = "PAPER-REQ-0001"
type = "analysis_request"
title = "Add sheath width comparison for Figure 2"
paper_id = "draft-a"
paper_context = "Results / Figure 2"
desired_artifact = "table or figure comparing sheath width across angle_scan"
source_link = "refs/links.toml#paper.draft-a"
related_runs = ["R20260412-0003"]
related_surveys = ["runs/sheath/angle_scan"]
priority = "medium"
status = "open"
human_gate = true
```

空の queue では `[[requests]]` を省略し、`schema_version = 1` だけを置ける。

`type` は `analysis_request`, `figure_request`, `experiment_request`,
`evidence_gap`, `export_request` のいずれかにする。

## Routing

- 軽い解析・図表・export 要望は `research/agenda.md` の current decision /
  next action に要約して追う。
- 高コスト rerun、新しい survey、paper-level claim に関わる要望は
  `research/proposals/` に proposal を作ってから進める。
- `experiment_request` は case / survey design までを計画し、MCP 経由で勝手に
  submit しない。

## MCP

- `runops.paper.requests.list` は request queue を read-only に列挙する。
- `runops.paper.request.plan` は 1 件の request を agenda / proposal へ戻す
  plan を返す。file mutation、run creation、job submit は行わない。
- 図表候補や export 候補の確認は `runops.analysis.artifacts`,
  `runops.survey.summary`, `runops.publication.exports.list` を使う。
