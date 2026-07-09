# notes/ — lab notebook & reports

`notes/` は **逐次的な実験ノートと長文レポート** を入れる、人間/Agent 共有の
作業場です。論文 PDF、manual、図、snippet などの source material は隣の
`materials/` に置きます。現在の高レベルな研究判断は `research/agenda.md` に
置きます。

`.runops/knowledge/` は simulator/environment plugin、明示的 knowledge source、
任意の `refs/` fallback mirror などから生成する Agent context です。
`.runops/insights/` と `.runops/facts.toml` は
互換性のため残る advanced/structured knowledge store と考え、日常のメモや
レポートはまず `notes/`, `materials/`, `research/` に置くのを推奨します。

## どこに何を書くか

| 場所                          | 用途                                     | 性質                |
| ---                           | ---                                      | ---                 |
| **`notes/YYYY-MM-DD.md`**     | **日次の lab notebook (append-only)**    | **chronological**   |
| `notes/history/YYYY/YYYY-MM-DD.md` | 古い日次 lab notebook の archive     | chronological       |
| **`notes/reports/README.md`** | **report の reading order / entry point** | **index, 改稿可**   |
| **`notes/reports/<topic>.md`**| **長文レポート / 解析記事**              | **refined, 改稿可** |
| `notes/reports/archive/`      | 旧版 report / full log                   | recovery-only       |
| `notes/reports/figures/`      | report 専用の代表図                      | report-owned        |
| `analysis/cross_run/<comparison_id>/` | 複数 run 比較の data / figures / reports | machine artifact |
| **`research/agenda.md`**      | **現在の高レベルな研究判断**             | **mutable ledger**  |
| **`materials/`**              | **論文・manual・図・snippet**            | **source material** |
| `.runops/knowledge/`          | 生成済み Agent context                   | generated, internal |
| `.runops/facts.toml`          | 機械可読 atomic claim                    | advanced, structured |
| `.runops/insights/<name>.md`  | 名前付き整理済知見 (`/learn` で書く)     | advanced, durable   |
| `runs/<run>/analysis/`        | 個別 run の curated 出力                 | run 単位            |

## 規約

### 日次 lab notebook (`notes/YYYY-MM-DD.md`)

- **append-only**: 新しい entry を **末尾に追記**する。過去の entry は触らない
- 1 ファイル = 1 日。日付は ISO 形式 (`2026-04-08.md`)
- 直近の active notebook は `notes/` 直下に置く。古い notebook は
  `runo notes archive --older-than 7d` で `notes/history/YYYY/YYYY-MM-DD.md`
  に移す
- 各 entry は `## HH:MM <TYPE object — action/claim>` で始まる
- 目的は「短い時系列ログ」ではなく、**短いが後続の人間/Agent が再開できるログ**にすること
- title の TYPE は `DESIGN`, `MODEL`, `EXEC`, `STATUS`, `ANALYSIS`, `FIGURE`, `DEBUG`, `DECISION`, `HANDOFF` を推奨

#### 再開可能な entry の最低条件

- 冒頭に `Context:` を置き、campaign / survey / run / model / purpose を分かる範囲で書く
- model 名だけで済ませない。1 行定義、または model card / report / case / survey への link を付ける
- 数値・図・結論・異常判定には `Evidence:` として run、manifest、summary、script、figure、CSV、stdout/stderr などの path を付ける
- 図を生成したら原則 Markdown image (`![caption](relative/path.png)`) で埋め込み、caption、observation、interpretation、caveat を添える。リンクだけで代替せず、人間が Markdown だけで図を確認できるようにする。大量図は contact sheet または代表図にする
- `Observation:` は見えた事実、`Interpretation:` は推測・仮説、`Caveat/Next:` は未確認点と次の一手に分ける
- 不明点は曖昧に省略せず、`unknown` / `not checked` として残す

例:

```markdown
## 14:32 ANALYSIS Series A — cs scaling preview

Context: campaign=ion-angle; survey=runs/series_a; run=R20260408-0001..0003; model=flat_plate baseline (case: cases/flat_plate/case.toml); purpose=quick check before submitting Series B.

Action: Collected 3 completed summaries and fit tan(alpha) against cs/vflow.
Evidence: summary=runs/series_a/summary/survey_summary.csv; script=runs/series_a/summary/fit_alpha.py.
Observation: `tan α = 0.79 (cs/vflow) + 0.02`, R^2=0.9997; vti-only fit has R^2=0.991.
Interpretation: cs/vflow is the stronger organizing variable for this subset.
Caveat/Next: Only 3 points; confirm after Series B completes.
```

### 長文レポート (`notes/reports/<topic>.md`)

- 1 トピック = 1 ファイル
- 何度書き直してもよい (lab notebook と違って refined)
- `notes/reports/README.md` に reading order と主要 entry point を残す。
  人間や次の Agent が Markdown だけを読んで現在の report 群に戻れるようにする
- 図は `notes/reports/figures/` に置くか、`analysis/cross_run/<id>/figures/` への相対 link
- 代表図は Markdown image として本文に埋め込み、外部リンク一覧だけにしない。
  人間が Markdown だけで図を確認できる状態を基本にする
- 完成度が高くなってから `runo analyze export --paper <paper-id>` で
  `exports/papers/<paper-id>/` に束ね、paper repo に移送する

### Cross-run artifact (`analysis/cross_run/<comparison_id>/`)

- 複数 run 比較、paper material bundle、再生成可能な CSV / plot / script / log は
  `analysis/cross_run/<comparison_id>/` に置く。
- 推奨構造は `README.md`, `data/`, `figures/`, `reports/`, `scripts/`, `logs/`。
- 人間が読む narrative は `notes/reports/<topic>.md`、現在判断は
  `research/agenda.md` に分ける。`agenda.md` は artifact list ではない。

## 補助コマンド

- **`runo notes append "<title>" "<body>"`** — 今日の `notes/YYYY-MM-DD.md`
  に新しい entry を append する。`-` または引数省略で stdin から本文を読む
- **`runo notes list`** — active と history の lab notebook 日付一覧
- **`runo notes show [DATE|today|latest]`** — active と history から指定日の内容を表示
- **`runo notes archive --older-than 7d`** — 古い active notebook を
  `notes/history/YYYY/` に移す (`notes/reports/` は触らない)
- **`/note` skill** — agent から呼んで note を append (内部で `runo notes append` を呼ぶ)

## なぜ `runo knowledge save` ではダメか

- `knowledge save` は **同名で書くと上書き** で chronology と相性が悪い
- knowledge commands は structured / advanced な用途に向いていて、「今日試したこと
  のメモ」や「読みかけ論文の要約」とは shape が違う
- 個別 fact / insight として機械的に再利用する価値が出てきたら、そのときに
  `/learn` で `.runops/insights/` や `facts.toml` に移送すればよい

## 昇格パス

```
materials/                  ← source material (papers, manuals, snippets)
        ↓ (読んだこと・観察したことを記録)
notes/YYYY-MM-DD.md          ← 日次の observation / work log
notes/history/YYYY/YYYY-MM-DD.md
                              ← 古い日次 notebook
        ↓ (ストーリーが固まる)
notes/reports/<topic>.md     ← 整理済 long form report
research/agenda.md           ← 現在の見立て / active question / 次の判断
        ↓ (機械的に再利用したい atomic な知見だけ抽出)
.runops/insights/<name>.md   ← advanced: named insight
.runops/facts.toml           ← advanced: machine-readable claim
```
