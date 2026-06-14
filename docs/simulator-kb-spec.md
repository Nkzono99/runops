# Simulator Cookbook Spec (v0.2)

simulator 側の plugin / knowledge source / 任意 mirror が、AI Agent や管理ツールに
ツール非依存の入力例・設定カタログを提供するための規約。

plugin-first な運用では、cookbook の本文と長文 workflow は simulator 側 Codex plugin
または明示的 knowledge source が提供する。runops 本体は cookbook 本文を内包せず、
`runo plugins --json` の `delegated_capabilities["cookbook"]` と推薦 metadata で
委譲先を案内する。`refs/` は offline 利用、private repo、開発中 checkout を近くに
置くための fallback mirror として扱う。

## 目的

- 典型的な入力例を構造化して提供する
- 用途別プリセットとして再利用可能にする
- パラメータ生成の出発点を Agent に与える
- 部分設定 (fragment) の安全な合成を可能にする
- ツール固有の知識ではなく、simulator 固有の知識として管理する

## 原則

- **ツール非依存**: 特定の管理ツールに依存しない。どの AI Agent やワークフローツールからでも参照できる
- **自己記述的**: cookbook 自体が構造と使い方を説明する (`COOKBOOK.md`)
- **軽量**: 大きな DB ではなく、構造化ディレクトリ + 薄い目録
- **example が主役**: 完全な入力例を中心に、fragment は補助
- **人間可読 + 機械可読**: メタデータは TOML、補足は Markdown
- **正本は meta.toml**: index.toml は discovery 用の薄い射影

## ディレクトリ構成

```text
provider-repo/
  cookbook/
    COOKBOOK.md              # 管理ガイド (人間・保守 Agent 向け)
    index.toml              # discovery 用目録
    examples/
      electrostatic/
        sheath-basic/
          meta.toml         # entry 正本
          input.toml        # 完全な入力ファイル
          README.md         # 人間向け補足 (GitHub で自動表示)
      electromagnetic/
        alfven-wave/
          meta.toml
          input.toml
    fragments/
      boundary/
        absorbing-open/
          meta.toml
          fragment.toml     # 部分設定
      diagnostics/
        quick-look/
          meta.toml
          fragment.toml
```

## 必須要件

- `cookbook/COOKBOOK.md` は必須
- `cookbook/index.toml` は必須
- 各 example / fragment ディレクトリは `meta.toml` を持つ
- 各 entry は repo 内で安定な `id` を持つ

## 読取順序

### Agent / ツール

1. runops project では `runo plugins --json` の `delegated_capabilities["cookbook"]` で委譲先を確認する
2. simulator/environment plugin、または明示的 knowledge source が提供する cookbook guide を読む
3. raw cookbook tree を直接読む場合は `index.toml` で全 entry を一覧し、`tags` / `recommended_for` / `status` で候補を絞る
4. 候補 entry の `meta.toml` で詳細を確認
5. `input.toml` / `fragment.toml` の実ファイルを読む
6. 必要なら `README.md` で注意事項を確認

### 人間 / 保守者

1. `COOKBOOK.md` で概要と管理手順を把握
2. `index.toml` で entry を探す
3. entry ディレクトリの `README.md` を読む

## `COOKBOOK.md`

cookbook ディレクトリのルートに置く。2 つの役割がある:

1. **この cookbook の概要**: どんな simulator の、どんな入力例が入っているか
2. **管理ガイド**: repo 側の Agent や開発者が entry を追加・更新する手順

Agent が毎回読む必要はない。
保守者向けの運用ドキュメントとして機能する。

後述の「COOKBOOK.md テンプレート」節を参照。

---

## `index.toml`

discovery 用の薄い目録。正本は各 entry の `meta.toml`。

`index.toml` には候補選定に必要な最小限のフィールドだけを置く。
`title` や `summary` は `meta.toml` にのみ書き、index には複製しない。

```toml
[cookbook]
schema_version = "0.2"
software = "MPIEMSES3D"

[[entries]]
id = "electrostatic-sheath-basic"
kind = "example"
path = "examples/electrostatic/sheath-basic"
tags = ["electrostatic", "sheath", "1d", "baseline"]
recommended_for = ["sanity-check", "parameter-sweep-base"]
status = "stable"

[[entries]]
id = "quick-look-diagnostics"
kind = "fragment"
path = "fragments/diagnostics/quick-look"
tags = ["diagnostics", "smoke-test"]
recommended_for = ["baseline", "debug"]
status = "stable"
```

### `[cookbook]`

| フィールド | 必須 | 説明 |
|---|---|---|
| `schema_version` | yes | この仕様のバージョン (`"0.2"`) |
| `software` | yes | 対象ソフトウェア名 |

### `[[entries]]`

| フィールド | 必須 | 説明 |
|---|---|---|
| `id` | yes | 安定な識別子 (rename しない) |
| `kind` | yes | `example` / `fragment` |
| `path` | yes | index.toml からの相対パス |
| `tags` | yes | 検索用タグ |
| `recommended_for` | no | 推奨用途 |
| `status` | yes | `draft` / `stable` / `deprecated` |

**index.toml に置かないもの**: `title`, `summary`, `applicability`, `recommended`, `files`。
これらは `meta.toml` にのみ書く。

### index.toml の管理

- 小規模 repo: 手書きで可
- 中規模以上: `meta.toml` 群から自動生成することを推奨

---

## `meta.toml` (example)

各 entry の正本。entry の定義、用途、実行可能性を記述する。

```toml
schema_version = "0.2"
id = "electrostatic-sheath-basic"
kind = "example"
title = "Basic electrostatic sheath"
summary = "Minimal 1D sheath for quick testing."
entry_version = "1.0"
status = "stable"

[files]
input = ["input.toml"]

[applicability]
model = "electrostatic"
geometry = "1d"
boundary = "absorbing"

[recommended]
use_for = ["baseline", "small-test", "parameter-sweep-base"]
vary_first = ["tmgrid.dt", "tmgrid.nx", "species.0.density"]
keep_fixed = ["boundary.type"]
avoid_if = ["strongly electromagnetic phenomena"]

[edit_policy]
safe_to_modify = ["tmgrid.dt", "tmgrid.nx"]
sensitive = ["species.0.mass_ratio"]
immutable = ["boundary.type"]

[validation]
runnable = true
verification_level = "smoke"

[cost]
scale = "small"

[lineage]
derived_from = []
rationale = ""
```

### 必須項目

- `schema_version`
- `id`
- `kind`
- `title`
- `status`

### トップレベルフィールド

| フィールド | 必須 | 説明 |
|---|---|---|
| `schema_version` | yes | `"0.2"` |
| `id` | yes | index.toml の `id` と一致 |
| `kind` | yes | `example` / `fragment` |
| `title` | yes | 人間向け表示名 |
| `summary` | no | 一文の説明 |
| `entry_version` | no | entry 内容のバージョン (例: `"1.0"`, `"1.1"`) |
| `status` | yes | `draft` / `stable` / `deprecated` |

### `[files]`

| フィールド | 説明 |
|---|---|
| `input` | 完全入力例または fragment ファイル一覧 |
| `related` | 参照したい追加ファイル |

ファイル名は自由。推奨:
- example: `input.toml` (またはシミュレータ固有名 `plasma.toml` 等)
- fragment: `fragment.toml`

人間向け補足は `README.md` としてディレクトリに置く。
GitHub でディレクトリを開いたときに自動レンダリングされる。
`[files]` には含めない (暗黙の規約)。

### `[applicability]`

この entry が想定するモデル・用途。

語彙は simulator ごとに拡張してよいが、以下の推奨 enum を優先する。
自由記述は `README.md` に書く。

| フィールド | 推奨値 | 説明 |
|---|---|---|
| `model` | `electrostatic`, `electromagnetic`, `hybrid`, `mhd` | 物理モデル |
| `geometry` | `1d`, `2d`, `2d3v`, `3d` | 空間次元 |
| `boundary` | `absorbing`, `periodic`, `reflecting`, `open` | 境界条件 |
| `flow` | `none`, `solar-wind`, `beam`, `drift` | 流入条件 |
| `magnetized` | `true`, `false` | 磁場の有無 |
| `collisions` | `none`, `coulomb`, `mcc` | 衝突モデル |

simulator 固有のフィールドを追加してよい。
`COOKBOOK.md` のタグ一覧で repo 内の語彙を管理する。

### `[recommended]`

Agent がパラメータ生成に使う補助情報。

| フィールド | 説明 |
|---|---|
| `use_for` | 推奨用途 |
| `vary_first` | 最初に振るべきパラメータ (dot 記法) |
| `keep_fixed` | 固定すべきパラメータ |
| `avoid_if` | この例を使うべきでない状況 |
| `clone_from` | ベースにした他 entry の id |

### `[edit_policy]`

パラメータの編集安全性を機械可読に示す。

| フィールド | 説明 |
|---|---|
| `safe_to_modify` | 自由に変更してよいパラメータ |
| `sensitive` | 変更時に注意が必要なパラメータ |
| `immutable` | 変更してはいけないパラメータ |

### `[validation]`

この example がどの程度検証済みかを示す。

| フィールド | 説明 |
|---|---|
| `runnable` | `true`: そのまま実行できる。`false`: 調整が必要 |
| `last_verified_with` | 検証に使ったソフトウェアバージョン (例: `"MPIEMSES3D 2.3.1"`) |
| `verification_level` | `smoke`: 起動確認のみ。`regression`: 結果の再現性確認済み。`production`: 本番品質 |

### `[cost]`

計算コストの目安。Agent の提案精度に影響する。

| フィールド | 説明 |
|---|---|
| `scale` | `tiny`, `small`, `medium`, `large` |
| `expected_runtime` | 概算実行時間 (例: `"5m"`, `"2h"`) |
| `expected_memory` | 概算メモリ (例: `"2GB"`) |
| `gpu_required` | `true` / `false` |
| `mpi_ranks` | MPI 並列数の目安 (例: `"1-4"`, `"16"`) |

### `[lineage]`

この entry の派生元を記録する。

| フィールド | 説明 |
|---|---|
| `derived_from` | 派生元 entry の id リスト |
| `rationale` | 派生の理由 |

---

## `meta.toml` (fragment)

fragment は example と異なり、合成契約 `[merge]` と互換性 `[compatibility]` を持つ。

```toml
schema_version = "0.2"
id = "quick-look-diagnostics"
kind = "fragment"
title = "Quick-look diagnostics"
summary = "Minimal diagnostics for smoke tests."
entry_version = "1.0"
status = "stable"

[files]
input = ["fragment.toml"]

[merge]
strategy = "deep-merge"
targets = ["diagnostics"]
conflicts_with = ["full-diagnostics"]

[compatibility]
requires_tags = ["electrostatic"]
forbids_tags = ["production-template"]

[recommended]
use_for = ["baseline", "debug"]
```

### `[merge]`

fragment を example に合成する際の契約。

| フィールド | 必須 | 説明 |
|---|---|---|
| `strategy` | yes | `deep-merge`: 深いマージ。`replace`: 対象セクションを置換。`append`: リストに追記 |
| `targets` | yes | 合成先のセクション名 (TOML のキーパス) |
| `conflicts_with` | no | 同時に使えない fragment の id リスト |

### `[compatibility]`

この fragment が適用可能な条件。

| フィールド | 説明 |
|---|---|
| `requires_tags` | 適用先 example が持つべきタグ |
| `forbids_tags` | 適用先 example が持ってはいけないタグ |

`requires_tags` / `forbids_tags` は index.toml の `tags` と照合する。

---

## `kind`

| kind | 説明 |
|---|---|
| `example` | 完全な入力例。Agent の第一候補。そのまま実行できる |
| `fragment` | 部分設定。example に合成して使う。単体では実行できない |

`note` kind は v0.2 では廃止。
入力を伴わない補助資料は `README.md` または `docs/` に置く。

---

## `recommended_for` 推奨語彙

| 値 | 説明 |
|---|---|
| `sanity-check` | 動作確認 |
| `baseline` | 基準設定 |
| `parameter-sweep-base` | サーベイの出発点 |
| `small-test` | 小規模テスト |
| `debug` | デバッグ用 |
| `production-template` | 本番計算のテンプレート |

自由な値も許容するが、上記を優先する。

## `status`

| 値 | 説明 |
|---|---|
| `draft` | 作成中。動作未保証 |
| `stable` | 検証済み。安定して使える |
| `deprecated` | 非推奨。新しい entry を使うこと |

---

## ID と互換性

- `id` は rename しない
- 内容を更新しても `id` は維持し、`entry_version` を上げる
- 破壊的な意味変更をするときは新しい `id` を作り、旧 entry を `deprecated` にする
- `schema_version` が変わるときは下位互換性の有無を `COOKBOOK.md` に書く

## 最小導入セット

最初の導入では次で十分:

1. `cookbook/COOKBOOK.md`
2. `cookbook/index.toml`
3. 2〜5 個の representative examples (各 `meta.toml` + `input.toml`)

fragment、`[validation]`、`[cost]`、`[lineage]` は後から足してよい。
最初は `[files]` + `[applicability]` + `[recommended]` だけで十分。

## 非目標

- 中央集約型データベース
- 厳密な検索言語
- 全 simulator 共通の完全語彙統制
- 制約チェック (利用側ツールの責務)
- バリデーションルールの定義

制約・バリデーションは cookbook の外で管理する。
cookbook は「何をどう使うか」だけに集中する。

---

## COOKBOOK.md テンプレート

以下は simulator repo、simulator plugin の context repository、または明示的
knowledge source の `cookbook/COOKBOOK.md` に置くテンプレート。
`{...}` はリポジトリに合わせて書き換える。

````markdown
# {Software Name} Cookbook

{Software Name} の入力例・設定フラグメント集。
AI Agent や開発者が入力ファイルを生成する際の出発点として使う。

## 構成

```
cookbook/
  COOKBOOK.md        # このファイル
  index.toml        # discovery 用目録
  examples/         # 完全な入力例
  fragments/        # 再利用可能な部分設定
```

## 使い方

### Agent / ツール

1. plugin / knowledge source の guide でこの cookbook の位置づけを確認する
2. `index.toml` を読んで、`tags` / `recommended_for` / `status` で候補を絞る
3. 候補 entry の `meta.toml` で用途と適用条件を確認する
4. `input.toml` (または `fragment.toml`) を読む
5. 必要なら `README.md` で注意事項を確認する

### 人間

1. `index.toml` で目的に合う entry を探す
2. entry ディレクトリの `README.md` を読む
3. `input.toml` をコピーして使う

## entry の追加手順

### 1. ディレクトリを作る

example の場合:
```bash
mkdir -p cookbook/examples/{category}/{entry-name}
```

fragment の場合:
```bash
mkdir -p cookbook/fragments/{category}/{entry-name}
```

### 2. meta.toml を書く

example の場合:
```toml
schema_version = "0.2"
id = "{category}-{entry-name}"
kind = "example"
title = "{人間向けタイトル}"
summary = "{一文の説明}"
entry_version = "1.0"
status = "draft"

[files]
input = ["{入力ファイル名}"]

[applicability]
model = "{model}"
geometry = "{geometry}"

[recommended]
use_for = ["baseline"]
vary_first = ["{パラメータ}"]

[cost]
scale = "small"
```

fragment の場合は `[merge]` と `[compatibility]` を追加する:
```toml
[merge]
strategy = "deep-merge"
targets = ["{合成先セクション}"]
conflicts_with = []

[compatibility]
requires_tags = ["{必要なタグ}"]
forbids_tags = []
```

### 3. 入力ファイルを置く

- example: そのまま実行できる完全な入力ファイルを `input.toml` として置く
  - simulator 固有の名前 ({simulator の入力ファイル名}) でもよい
- fragment: 他の入力に合成して使う部分設定を `fragment.toml` として置く

### 4. README.md を書く (推奨)

- この entry の意図、背景、注意事項を書く
- パラメータの選定理由があれば書く
- 既知の制限があれば書く
- fragment の場合は「単体では実行できない」ことを明記する

### 5. index.toml に登録する

```toml
[[entries]]
id = "{meta.toml の id と一致}"
kind = "example"
path = "examples/{category}/{entry-name}"
tags = ["{タグ}"]
recommended_for = ["{推奨用途}"]
status = "draft"
```

### 6. 検証して status を stable に上げる

example の場合:
1. そのまま実行できることを確認する
2. `meta.toml` の `[validation].runnable = true` を設定する
3. `meta.toml` と `index.toml` の `status` を `"stable"` に変更する

## entry の更新

- `id` は変えない
- 内容を改善するときは `meta.toml` の `entry_version` を上げる
- 破壊的な変更は新しい `id` で別 entry を作り、旧 entry を `deprecated` にする

## 品質基準

- example は **そのまま実行できる** こと (`status = "stable"` の場合)
- `meta.toml` の `vary_first` には、実際に振って意味のあるパラメータだけを書く
- `tags` は既存 entry と語彙を揃える (下記「タグ一覧」を確認)
- fragment は **単体では実行できない** ことを `README.md` に明記する
- fragment は `[merge]` と `[compatibility]` を必ず定義する

## applicability 推奨値

| フィールド | 推奨値 |
|---|---|
| `model` | `electrostatic`, `electromagnetic`, `hybrid`, `mhd` |
| `geometry` | `1d`, `2d`, `2d3v`, `3d` |
| `boundary` | `absorbing`, `periodic`, `reflecting`, `open` |
| `flow` | `none`, `solar-wind`, `beam`, `drift` |
| `magnetized` | `true`, `false` |

{ソフトウェア固有のフィールドがあればここに追加する。}

## タグ一覧

{このリポジトリで使われているタグを列挙する。新しいタグを追加したらここも更新する。}

## 仕様

この cookbook は [Simulator Cookbook Spec v0.2](https://github.com/Nkzono99/runops/blob/main/docs/simulator-kb-spec.md) に準拠する。
````
