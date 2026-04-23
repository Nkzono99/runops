# notes/ — lab notebook & reports

`notes/` は **逐次的な実験ノートと長文レポート** を入れる、人間/Agent 共有の
作業場です。論文 PDF、manual、図、snippet などの source material は隣の
`materials/` に置きます。

`.runops/knowledge/` は `runo update-refs` や `runo knowledge source render` が
生成する Agent context です。`.runops/insights/` と `.runops/facts.toml` は
互換性のため残る advanced/structured knowledge store と考え、日常のメモや
レポートはまず `notes/` と `materials/` に置くのを推奨します。

## どこに何を書くか

| 場所                          | 用途                                     | 性質                |
| ---                           | ---                                      | ---                 |
| **`notes/YYYY-MM-DD.md`**     | **日次の lab notebook (append-only)**    | **chronological**   |
| **`notes/reports/<topic>.md`**| **長文レポート / 解析記事**              | **refined, 改稿可** |
| **`materials/`**              | **論文・manual・図・snippet**            | **source material** |
| `.runops/knowledge/`          | 生成済み Agent context                   | generated, internal |
| `.runops/facts.toml`          | 機械可読 atomic claim                    | advanced, structured |
| `.runops/insights/<name>.md`  | 名前付き整理済知見 (`/learn` で書く)     | advanced, durable   |
| `runs/<run>/analysis/`        | 個別 run の curated 出力                 | run 単位            |

## 規約

### 日次 lab notebook (`notes/YYYY-MM-DD.md`)

- **append-only**: 新しい entry を **末尾に追記**する。過去の entry は触らない
- 1 ファイル = 1 日。日付は ISO 形式 (`2026-04-08.md`)
- 各 entry は `## HH:MM <短いタイトル>` で始まる
- 内容は自由 (試したこと, 見たこと, 仮説, 失敗, TODO, etc.)
- 思考の chain of thought を残しておく場所と思えばよい

例:

```markdown
## 14:32 cs scaling preview

3 点で `tan α = 0.79 (cs/vflow) + 0.02, R² = 0.9997` が出た。vti scaling
(R² = 0.991, intercept 0.073) より明らかに良い。3 点だけなのが心配。
Series B 完走で確かめる。
```

### 長文レポート (`notes/reports/<topic>.md`)

- 1 トピック = 1 ファイル
- 何度書き直してもよい (lab notebook と違って refined)
- 図は `notes/reports/figures/` に置くか、`runs/_compare_*/` への相対 link
- 完成度が高くなってから `runo analyze export --paper <paper-id>` で
  `exports/papers/<paper-id>/` に束ね、paper repo に移送する

## 補助コマンド

- **`runo notes append "<title>" "<body>"`** — 今日の `notes/YYYY-MM-DD.md`
  に新しい entry を append する。`-` または引数省略で stdin から本文を読む
- **`runo notes list`** — 最近の lab notebook 日付一覧
- **`runo notes show [DATE|today|latest]`** — 指定日 (省略時は today) の内容を表示
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
        ↓ (ストーリーが固まる)
notes/reports/<topic>.md     ← 整理済 long form report
        ↓ (機械的に再利用したい atomic な知見だけ抽出)
.runops/insights/<name>.md   ← advanced: named insight
.runops/facts.toml           ← advanced: machine-readable claim
```
