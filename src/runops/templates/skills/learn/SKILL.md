---
name: learn
description: Save advanced knowledge insights and structured facts from experiment results. Use only after notes/ or reports/ contain stable findings worth machine reuse.
---

# 実験結果から知見を記録する

`{{ skill_prefix }}learn` は advanced / structured knowledge
(`.runops/insights/`, `.runops/facts.toml`) への永続化スキル。これに対して
`{{ skill_prefix }}note` は raw な lab notebook (`notes/`) への時系列追記で、
論文・manual・図・snippet などの source material は `materials/` に置く。

日常の知識共有はまず `notes/` と `materials/` に寄せる。`{{ skill_prefix }}learn`
は **機械的に再利用したい、安定した知見だけを抽出する** ときに使う。

## 手順

1. **`notes/` と `materials/` を素材として集める** (structured knowledge を作る前段)
   - `runo notes list` で最近の lab notebook 日付を確認
   - 関連するテーマの `runo notes show <YYYY-MM-DD>` で読む
   - `materials/index.toml` や `materials/README.md` で関連資料を確認
   - 散らばった観察・仮説・反例・却下案を集める
2. 完了した run の結果 (`runo analyze summarize`, ログ, 出力) を読む
3. 新たに分かったこと・期待と異なる結果を特定する
4. 知見の種類を判断する (constraint / result / analysis / dependency)
5. 出処になった `notes/<date>.md` の日付を insight 本文に書き残す
   (後から検証可能・raw material trail として)

## 人向け知見の保存

```bash
runo knowledge save <name> -t <type> -s <simulator> -m "<内容>"
```

タイプ: `constraint`, `result`, `analysis`, `dependency`

例:

```bash
runo knowledge save mag_scan_summary -t result -s emses \
  -m "磁場角度 0-90 度のサーベイ。45度で最もイオン加速が効率的。"
```

## 機械可読な fact の追加

```bash
runo knowledge add-fact "<claim>" \
  -t <type> -s <simulator> \
  --param-name <param> --scope-text "<scope>" \
  --evidence-kind <kind> --evidence-ref <ref> \
  -c <confidence> --tags "<tags>"
```

タイプ: `observation`, `constraint`, `dependency`, `policy`, `hypothesis`

- `high` confidence は複数 run の再現か deterministic 確認がある場合だけ使う
- 既存 fact を修正するときは `--supersedes fNNN` を使う
- 外部 source から同期された candidate fact は `runo knowledge facts` で確認できる
- 採用する candidate fact は `runo knowledge promote-fact <source>:<fact_id>` で local fact に昇格する
