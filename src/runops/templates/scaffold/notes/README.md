# notes/ — lab notebook & reports

`.runops/insights/` と `.runops/facts.toml` は **curated knowledge** (整理済の
名前付き知見) を入れる場所。本ディレクトリ `notes/` は **逐次的な実験ノート
と長文レポート** を入れる場所で、両者は明確に役割を分ける。

## どこに何を書くか

| 場所                          | 用途                                     | 性質                |
| ---                           | ---                                      | ---                 |
| `.runops/facts.toml`          | 機械可読 atomic claim                    | curated, atomic     |
| `.runops/insights/<name>.md`  | 名前付き整理済知見 (`/learn` で書く)     | curated, durable    |
| **`notes/YYYY-MM-DD.md`**     | **日次の lab notebook (append-only)**    | **chronological**   |
| **`notes/reports/<topic>.md`**| **長文レポート / 解析記事**              | **refined, 改稿可** |
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
- knowledge は「最終的な findings」を整理する場所であって、「今日試したこと
  のメモ」は意味的にも違う
- 個別 fact / insight に昇格する価値が出てきたら、そのときに `/learn` で
  knowledge layer に移送すればよい

## 昇格パス

```
notes/YYYY-MM-DD.md          ← 日次の chain of thought
        ↓ (ストーリーが固まる)
notes/reports/<topic>.md     ← 整理済 long form report
        ↓ (atomic な知見を抽出)
.runops/insights/<name>.md   ← 名前付き curated insight
.runops/facts.toml           ← 機械可読 atomic claim
```
