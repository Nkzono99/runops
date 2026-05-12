# Project Health Check

`runo lint` は runops project の運用品質を検査する command です。
`runo doctor` が実行環境を確認するのに対し、`runo lint` は Agent / 人間が読む
project state の整合性を確認します。

```bash
runo lint
runo lint --json
runo lint --scope structure,analysis,knowledge
runo lint --strict
```

## 役割

| Command | 役割 |
|---------|------|
| `runo doctor` | Python 環境、Slurm、site preset、`.runops/environment.toml` など実行環境を確認する |
| `runo context --json` | Agent が最初に読む project context を要約する |
| `runo lint` | project state が再開・解析・handoff 可能かを検査する |
| `runo migrate apply <id>` | migration guide に登録された定型修復を適用する |

`runo lint` は layer そのものではなく、Experiment / Execution / Analysis /
Research / Knowledge / Harness / Upstream の各 layer を横断して見る health check です。

## Scope

初期実装では次の scope を持ちます。

| Scope | 見るもの |
|-------|----------|
| `structure` | `campaign.toml`, `notes/README.md`, `research/agenda.md`, `.gitignore` managed block |
| `runs` | `manifest.toml` の読み取り、`run_id` の存在と一意性、manifest status と last Slurm state の矛盾 |
| `provenance` | completed run の `git_commit`, executable hash, simulator version |
| `analysis` | completed run の `analysis/summary.json`, artifact index, legacy `figures_index.json` |
| `knowledge` | `research/agenda.md` の template 状態、Next Actions の evidence path、`.runops/facts.toml` の source |

`--scope` は comma-separated です。

```bash
runo lint --scope structure
runo lint --scope analysis,knowledge
```

## Exit Code

- error があれば exit code `1`
- warning だけなら通常は exit code `0`
- `--strict` では warning でも exit code `1`

CI や preflight では `--strict` を使い、普段の作業では warning を見ながら必要なものだけ
直す運用を想定します。

## Migration との関係

lint finding に `Migration: M0-0001` のような表示がある場合、対応する定型 migration を
確認できます。

```bash
runo migrate show M0-0001
runo migrate apply M0-0001 --dry-run
runo migrate apply M0-0001
```

CLI で修復できない finding は、手作業で直すか、汎用化できそうなら `feedback-runops`
で HarnessOps record / upstream 下書きにします。

## Agent Workflow

Agent が project に入ったときの標準動線:

1. `runo context --json` で現在地を把握する。
2. 必要なら `runo lint --scope structure,analysis,knowledge` で読む入口と成果物索引を確認する。
3. migration finding があれば `runo migrate apply <id> --dry-run` で確認する。
4. 直したこと、skip したこと、保留したことを `notes/YYYY-MM-DD.md` に残す。
