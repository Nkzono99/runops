# SKILLS.md — runops Agent Skills Reference

AI エージェントが実行可能なスキル（操作手順）の定義。
各スキルは action registry の action を組み合わせた高レベル手順。

---

## Skill: パラメータサーベイの実行

**目的**: survey.toml から全 run を生成・投入・監視・集計する

### 手順

1. `runops context` で現在の project 状態を確認
2. survey.toml の内容を確認 (パラメータ軸と値)
3. `create_run` で各パラメータ組み合わせの run を生成
4. 各 run に対して `submit_run` で Slurm に投入
5. 定期的に `sync_run` で全 run の状態を更新
6. 失敗 run があれば `suggest_retry_for_run` で対処を判断
7. 全 run が completed になったら `collect_survey` で集計
8. 結果から得られた知見を `add_fact` で記録

### 注意点

- 一度に大量の run を投入しない (キューの公平性)
- timeout/oom の run は retry 前にパラメータを確認
- collect 前に全 run が completed/failed であることを確認

---

## Skill: 失敗 run の診断と復旧

**目的**: 失敗した run の原因を特定し、適切に再投入する

### 手順

1. `sync_run` で最新状態を取得
2. `show_log` でログの末尾を確認
3. manifest の `failure_reason` を確認
4. `suggest_retry_for_run` で推奨 action を取得
5. 原因に応じて対処:
   - **timeout**: walltime を 1.5倍に延長して `retry_run`
   - **oom**: メモリを 1.5倍にするか問題サイズ縮小
   - **preempted/node_fail**: そのまま `retry_run`
   - **exit_error**: ログから原因特定、修正後に `retry_run`
6. retry 結果を再度 `sync_run` で監視
7. 3回失敗したらユーザーに報告

### 注意点

- `exit_error` は必ずログを読んでから判断
- 同じ設定で3回失敗したら自動 retry を停止
- 原因が判明したら `add_fact` で知見を記録

---

## Skill: 知見の記録と活用 (`/learn`)

**目的**: 実験結果から得られた知見を curated 層 (`.runops/insights/`,
`.runops/facts.toml`) に永続化する

### 手順

1. **`notes/` を素材として読む** — `runops notes list` で日付一覧、
   関連日を `runops notes show <date>` で読んで散らばった観察・仮説・
   反例を集める
2. completed run の結果を `summarize_run` で確認
3. パラメータと結果の関係を分析
4. 知見を構造化:
   - `fact_type`: observation / constraint / dependency / policy / hypothesis
   - `simulator`: 対象シミュレータ
   - `scope_case`: 対象ケース
   - `param_name`: 関連パラメータ
   - `confidence`: high / medium / low
5. `add_fact` で記録、または `runops knowledge save` で markdown insight として保存
6. 既存 fact と矛盾する場合は `supersedes` で更新
7. 出処になった `notes/<date>.md` の日付を insight 本文に書き残す

### Confidence 判断基準

| Confidence | 条件 |
|-----------|------|
| high | 2件以上の独立 run で再現 |
| medium | 1件の明確な観測 |
| low | 暫定・推測を含む |

### 注意点

- hypothesis は fact_type="hypothesis" として明確に区別
- 1回の観測で high confidence にしない
- 数値的な制約は具体的な値を claim に含める

---

## Skill: 実験ノートの記録 (`/note`)

**目的**: 研究プロセスの各フェーズで生まれる raw chronological information
を `notes/YYYY-MM-DD.md` に append-only で残す。`/learn` の素材になる
chain of thought を失わないようにする。

### 手順

1. 何かしら新しい観察・意思決定・試行・議論があったら呼ぶ
2. 1-2 行の `<title>` と本文を `runops notes append` に渡す
3. 当該日付ファイルが無ければヘッダ付きで新規作成、あれば末尾に追記

```bash
# inline
runops notes append "<title>" "<body>"

# stdin / heredoc
runops notes append "<title>" - <<'EOF'
- A
- B
EOF
```

### いつ書くか — フェーズ別

**準備フェーズ (campaign / case / survey 設計)**:

- 意思決定の理由・トレードオフ・却下した代替案
- 資源見積もり・smoke test の選び方・不安な前提

**投入・実行フェーズ**:

- 投入 commit hash, run_id 範囲, queue, walltime
- 中断・再投入・OOM・kill の経緯と対処
- 暫定 status

**解析フェーズ**:

- 試したコマンドと結果 (1-3 行)
- 観察した数値・パターン
- 仮説、失敗、TODO、user との議論

### 注意点

- **append-only**: 既存 entry を書き換えない
- 1 entry = 1 トピック (混ぜない)
- curated 層に直接書こうとしない (まず `/note`, あとで `/learn`)
- 価値が出てきたら `notes/reports/<topic>.md` に refined version を書き、
  さらに `runops knowledge save` / `add-fact` で curated 化

---

## Skill: プロジェクト状態の把握

**目的**: プロジェクトの現在状態を素早く把握する

### 手順

1. `runo context --json` を実行
2. 返却された JSON から以下を確認:
   - `runs.failed`: 失敗 run の数
   - `runs.running`: 実行中 run の数
   - `runs.submitted`: 投入済み run の数
   - `recent_failures`: 最近の失敗原因
   - `facts`: 蓄積された知見
3. 優先度に基づいて次のアクションを決定

### 優先順位

1. submitted/running の run → `runo runs sync` で最新化
2. failed run → 診断・復旧
3. created run → `runo runs submit`
4. completed survey → `runo analyze collect`
5. 知見記録

---

## Skill: 継続 run の作成

**目的**: 完了した run のスナップショットから継続 run を作成する

### 手順

1. 元 run が completed であることを確認
2. `runo runs extend` で継続 run を生成
3. 新 run の manifest に `origin.parent_run` が設定されていることを確認
4. 必要に応じてパラメータを調整
5. `runo runs submit` で投入

---

## Action Quick Reference

```python
from runops.application.actions import execute_action

# Run 生成
result = execute_action("create_run", project_root=root, case_name="scan")

# Slurm 投入
result = execute_action("submit_run", run_dir=run_dir, queue_name="gr10451a")

# 状態同期
result = execute_action("sync_run", run_dir=run_dir)

# ログ確認
result = execute_action("show_log", run_dir=run_dir, lines=100)

# 解析サマリ
result = execute_action("summarize_run", run_dir=run_dir)

# Survey 集計
result = execute_action("collect_survey", survey_dir=survey_dir)

# 失敗 run の再投入
result = execute_action("retry_run", run_dir=run_dir, adjustments={"walltime_factor": 1.5})

# アーカイブ
result = execute_action("archive_run", run_dir=run_dir)

# 知見記録
result = execute_action("add_fact", project_root=root,
    claim="dt > 1e-8 causes instability in EMSES at nx=64",
    fact_type="constraint",
    simulator="emses",
    scope_case="mag_scan",
    param_name="dt",
    confidence="high",
    source_run="R20260330-0004",
    evidence_kind="run_observation",
    evidence_ref="run:R20260330-0004",
    tags=["stability", "cfl"],
)
```

## Retry Suggestion Quick Reference

```python
from runops.application.execution.retry import suggest_retry_for_run

suggestions = suggest_retry_for_run(run_dir)
for s in suggestions:
    print(f"  {s.action}: {s.rationale} (confidence: {s.confidence})")
```

## Context Bundle Quick Reference

```python
from runops.application.context import build_project_context

ctx = build_project_context(project_root)
print(ctx["runs"])              # state counts
print(ctx["recent_failures"])   # failed runs
print(ctx["facts"])             # knowledge facts
print(ctx["available_actions"]) # action registry
```
