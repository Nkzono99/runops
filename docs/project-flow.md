# AI Agent 前提の project 運用概念図

> このファイルは `python scripts/generate_agent_project_flow.py` で生成しています。
> 標準の再生成手順は `python scripts/render_diagrams_in_docker.py` です。

このガイドは、`runo init` で生成された project を人間と AI Agent がどう運用していくかを
概念図としてまとめたものです。

ポイントは、runops の project を単なる directory 群ではなく、
`研究意図`、`再利用テンプレート`、`実行状態`、`学習結果` を持つ運用系として捉えることです。

## 概念の対応表

| 層 / file | 概念上の役割 | Agent から見た意味 |
|---|---|---|
| [Experiment Layer](layers/experiment.md) | 実験設計 | campaign / case / survey の関係を決める。 |
| `campaign.toml` | 研究意図の正本 | 何を明らかにしたいか、どの変数を動かし、何を観測するかを Agent に渡す。 |
| `cases/**/case.toml` | 再利用可能な実験テンプレート | 共通の job 設定、ベース入力、固定パラメータを保持する。 |
| `runs/**/survey.toml` | サーベイ設計 | どの軸をどう振るか、命名や job override をどうするかを定義する。 |
| [Execution Kernel](layers/execution-kernel.md) | 実行状態の正本 | run 生成、submit、sync、manifest、provenance を扱う。 |
| `runs/**/Rxxxx/manifest.toml` | run の正本 | 各実行の state、origin、provenance、job 情報を記録する。 |
| [Analysis Layer](layers/analysis.md) | 解析・可視化成果物 | run summary、survey 集計、cross-run 比較を置く場所を決める。 |
| [Research Layer](layers/research.md) | 現在判断の台帳 | `research/agenda.md` に active question と current decision を残す。 |
| `refs/` | 外部知識と simulator docs | Agent が simulator 固有知識や cookbook を参照する入口。 |
| `materials/` | 人間提供の source material | 論文、manual、図、snippet を Agent と人間が見える場所に置く。 |
| `notes/**` | 作業ログとレポート | 日次 notebook と refined report を残す human/agent shared workspace。 |
| `.runops/knowledge/` | 生成済み Agent context | `imports.md` や candidate fact transport などの派生物。正本として手編集しない。 |
| `.runops/insights/` と `facts.toml` | advanced structured memory | 機械的に再利用したい整理済み知見だけを保存する互換/上級者向け層。 |
| [Knowledge Layer](layers/knowledge.md) | 再利用可能な知識 | refs、materials、notes、insights、facts の責務を分ける。 |
| [Harness Layer](layers/harness.md) | Agent 手順・権限・skills | `.claude/`, `.agents/`, `.codex/`, AGENTS/CLAUDE の責務を分ける。 |
| [Upstream Integration Layer](layers/upstream.md) | runops 本体への戻し口 | `tools/runops` local patch、feedback issue、PR、update conflict を扱う。 |

## `runo init` 後の project と Agent の見る世界

![runo init 後の project と Agent の見る世界](figures/agent-project-flow/init-world.png)

## AI Agent 前提の運用ループ

![AI Agent 前提の運用ループ](figures/agent-project-flow/operation-loop.png)

## 人が確認を入れるべきゲート

![人が確認を入れるべきゲート](figures/agent-project-flow/human-gates.png)

## 読み方の要点

- `runo init` 後の project は、Agent にとっての作業場であると同時に memory でもあります。
- レイヤーごとの正本は [docs/layers/README.md](layers/README.md) から辿れます。
- `campaign.toml` は研究意図、`case.toml` は再利用可能な基底条件、`survey.toml` は探索計画です。
- Execution Kernel は run 生成、submit、sync、manifest、provenance の実行状態正本です。
- `manifest.toml` は各 run の正本で、ここに state と provenance が残ります。
- `research/agenda.md` は現在の高レベルな研究判断の台帳です。TODO ではなく、
  active question、current decision、paused/killed、次に何をなぜ行うかを残します。
- 解析後の観察はまず `notes/` や `notes/reports/` に残し、機械的に再利用したいものだけ `insight` や `fact` として `.runops/` に戻します。
- つまり日常運用は `設計 -> 実行 -> 観測 -> 解析 -> 学習 -> 設計` のループです。

## 実務上のおすすめ

- 最初の依頼では、研究テーマ、仮説、独立変数、観測量、使いたいベース入力だけを Agent に渡す。
- run ごとの場当たり的な修正は避け、再利用価値がある変更は `campaign.toml`、`case.toml`、`survey.toml` に戻す。
- 毎回いきなり大量投入せず、Agent に `context` と `plan` を見せてもらってから初回 bulk submit に進む。
- 解析が終わったら `notes/` に観察を残し、必要なら `research/agenda.md` の
  current decision を更新する。機械的に再利用したい知見だけ `knowledge save`
  や `add-fact` で `.runops/` に昇格します。

## Git ignore と VS Code 表示

`runo init` は `.gitignore` と `.vscode/settings.json` の両方を生成します。
既存プロジェクトでは `runo update-harness` が `.vscode/settings.json` を再同期し、
`.gitignore` の runops managed block も更新します。managed block がまだ無い
既存 `.gitignore` には `.gitignore.new` を出して手動マージに回し、
`notes/`、`materials/`、`research/` の不足分も補完します。
この 2 つは役割が違います。

- `.gitignore` は Git に載せないものを決めます。`.venv/`、`tools/`、`refs/`、`runs/**/work/`、`.runops/knowledge/` などの再生成可能または大きい成果物を対象にします。
- VS Code の `files.exclude` は Explorer のノイズを減らします。`work/` は運用中にログや出力を直接確認しやすいよう見えるままにし、`status/`、`submit/`、`manifest.toml` などの内部状態だけを隠します。`campaign.toml`、`cases/**`、`runs/**/survey.toml`、`notes/**`、`materials/**`、`research/**` も見えるままにします。
- VS Code の `search.exclude` は検索ノイズを減らします。PDF などの人間が置いた資料は Explorer からは隠さず、検索対象からだけ外すのが基本です。
- `files.watcherExclude` と `python.analysis.exclude` は editor の負荷を下げるための設定で、runops の保護ルールや Git 管理とは別物です。
