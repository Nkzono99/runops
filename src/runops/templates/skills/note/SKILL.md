---
name: note
description: Append a timestamped entry to today's lab notebook in notes/YYYY-MM-DD.md. Use throughout the workflow — preparation (campaign / case / survey design decisions), execution, and analysis — for any chronological observation that doesn't yet belong in curated knowledge.
---

# 実験ノートを 1 件追記する

`{{ skill_prefix }}note` は today's `notes/YYYY-MM-DD.md` に **timestamped な短いエントリを
追記** する skill。**準備フェーズから解析フェーズまで**、研究プロセスの
全期間で使うことを想定している。source material (`materials/`) や advanced
structured knowledge (`{{ skill_prefix }}learn`, `runo knowledge save/add-fact`)
とは目的が違う:

| 用途 | スキル | 書き先 | 性質 |
|---|---|---|---|
| 試したこと、見たこと、仮説、TODO の **時系列ログ** | `{{ skill_prefix }}note` | `notes/YYYY-MM-DD.md` | append-only, chronological, scratch OK |
| 論文・manual・図・snippet の **source material** | (直接編集) | `materials/` | visible, inspectable |
| 整理済の **名前付き知見** | `{{ skill_prefix }}learn` | `.runops/insights/<name>.md` | advanced, durable, 上書き可 |
| 機械可読な **atomic claim** | `{{ skill_prefix }}learn` | `.runops/facts.toml` | advanced, atomic |

## 使い方

短いエントリ (タイトル + 本文) を取り、そのまま append:

```bash
runo notes append "<title>" "<body...>"
```

タイトルだけ引数で渡して本文は stdin から流す形:

```bash
runo notes append "<title>" -
# (stdin に本文を流す)
```

または heredoc:

```bash
runo notes append "<title>" - <<'EOF'
今日の作業まとめ
- A
- B
- C
EOF
```

書き込み先の決定:

- `notes/YYYY-MM-DD.md` (JST の今日)
- 既存ファイルの末尾に append, 無ければ "# YYYY-MM-DD — lab notebook" ヘッダ付きで新規作成
- 各エントリは `## HH:MM <title>` で始まる

## 関連コマンド

- `runo notes list` — 最近の lab notebook 日付一覧
- `runo notes show [DATE|today|latest]` — 指定日 (省略時は today) の内容を表示

## いつ書くか — フェーズ別ガイド

`{{ skill_prefix }}note` は **研究の各フェーズで `{{ skill_prefix }}note` を呼ぶ** ことを想定している。
解析時だけでなく、設計・準備時にも積極的に記録する。

### 準備フェーズ (campaign / case / survey 設計)

- **意思決定の理由**: なぜこの値・範囲・解像度を選んだか
  (e.g. "vti を 1-19 eV にしたのは CFL 4σ で 19 eV が上限だから")
- **設計トレードオフ**: 何と何を秤にかけて、何を切り捨てたか
  (e.g. "解像度 dx=0.5 m を維持するため、box を 4000×800 に縮めた")
- **却下した代替案**: 一度考えてやめたデザイン
  (e.g. "no_plate ケースは EMSES v4.9.0 では動かないので保留")
- **資源見積もり**: 想定 core-hour, queue, 投入順序の判断材料
- **検証計画**: smoke test の選び方、何を見れば成功・失敗が判定できるか
- **不安・前提**: 「ここが心配」「ここが勘」と思う部分の明文化

### 投入・実行フェーズ

- 投入したコマンド・対象 run・queue・資源量
- 中断・再投入の理由
- ジョブの異常 (kill, requeue, OOM, 異常終了) と対処
- 暫定 status (e.g. "夕方時点で 12/30 完走")

### 解析フェーズ

- 試したコマンド・スクリプトと結果 (1-3 行)
- 観察したこと (e.g. "alpha が R0036 で 6.13 deg")
- 仮説 (e.g. "intercept は sheath 厚由来かも")
- 失敗・つまづき
- TODO・次の一手
- 議論の流れ (user との対話で出てきた論点)

## 何を書かないか

- 論文 PDF / manual / figure / snippet → `materials/`
- 整理済の永続知見 → 必要な場合だけ `{{ skill_prefix }}learn` で `.runops/insights/`
- 1 つの atomic claim → 必要な場合だけ `{{ skill_prefix }}learn` で `.runops/facts.toml`
- 個別 run の curated 解析出力 → `runs/<run>/analysis/`

## 昇格ルール

lab notebook entry が積み上がって 1 つのストーリーになり、誰かに伝える価値が
出てきたら、

1. `notes/reports/<topic>.md` に refined version を書き起こす (改稿 OK)
2. 機械的に再利用したい部分だけ `{{ skill_prefix }}learn` で `.runops/insights/` / `facts.toml` に昇格

`{{ skill_prefix }}learn` は **`notes/` を素材として読む** ことを前提にしている (`{{ skill_prefix }}learn`
SKILL を参照)。つまり `{{ skill_prefix }}note` を高頻度で書いておくほど、後の `{{ skill_prefix }}learn` が
楽になる。

詳細規約: `notes/README.md`
