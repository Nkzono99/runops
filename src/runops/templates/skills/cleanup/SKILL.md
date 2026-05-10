---
name: cleanup
description: Archive completed runs, purge unnecessary work files, cancel running jobs, or hard-delete unused runs. Use for housekeeping after experiments.
---

# 完了・不要な Run を整理する

```bash
# 状態を確認
runo runs list $ARGUMENTS
```

## completed run の整理 (通常フロー)

```bash
# completed run をアーカイブ (既定で runs/_archive/ へ移動)
cd <run_dir>
runo runs archive

# パスを動かしたくない場合
runo runs archive --keep-in-place

# work/ の不要ファイルを削除 (archived のみ)
runo runs purge-work
```

## 実行中 job の停止

```bash
# scancel + sync を一回で。submitted/running の run を cancelled に遷移
runo runs cancel
```

## created / cancelled / failed の run を捨てる

```bash
# 失敗 run などをディレクトリごと削除 (completed/archived には使えない)
runo runs delete
```

## 注意

- `archive` / `purge-work` / `delete` は確認が必要な操作
- `archive` は既定で run ディレクトリを `runs/_archive/` に移す。既存のノートや
  スクリプトが古いパスを参照していないか確認する
- `cancel` は追加確認プロンプトなしで進めてよいが、実行前に対象と理由を必ず報告する
- `delete` は不可逆。`completed` / `archived` の run を捨てたい場合は
  `archive` → `purge-work` を使う
