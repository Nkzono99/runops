---
name: update-runops
description: Update runops itself and refresh harness files. Use when runops has a new release or harness templates need updating.
---

# runops を最新版に更新する

## 1. tools/runops を pull

```bash
cd tools/runops && git pull && cd -
```

`tools/runops` に未コミット変更、local branch、未 push commit がある場合、
`runo update-harness` は pull せず停止する。local patch を壊さないため、
`git reset --hard` での自動復旧は標準手順にしない。

停止した場合の選択肢:

- local patch をこの project で使い続ける
- `{{ skill_prefix }}patch-runops` で branch / commit / upstream disposition を整理する
- 設計が必要なら `{{ skill_prefix }}feedback-runops` で issue 化する
- 実装案を見せたいなら draft PR にする
- PR / rebase / stash / commit が終わってから改めて `update-runops`

## 2. ハーネスファイルを再生成

```bash
runo update-harness
```

- 未編集のファイルは自動で上書きされる
- ユーザーが編集済みのファイルは `<path>.new` として出力される → diff を確認してマージ
- `.vscode/settings.json` もこの更新対象に含まれる
- `notes/`, `materials/`, `research/` は不足している scaffold だけ補完される
- `--dry-run` で事前確認、`--force` で全上書き

## 3. シミュレータパッケージを更新

```bash
runo update
```

`runo update` は adapter が宣言する package spec に合わせて simulator
package を更新する。`refs/<simulator>/` を editable install して simulator
本体を開発している場合は、更新前に warning と確認が出る。

- git-pinned / package install が通常運用。再現性と provenance を優先する
- editable install は simulator 本体を修正・debug するときだけの opt-in
- editable を package spec に戻してよい場合だけ `runo update --yes` または
  `runo update --force` を使う

## 一括実行

```bash
runo update-harness && runo update
```

`update-harness` が内部で `tools/runops` の `git pull` も行うため、手順 1 を個別に実行する必要はない。

## 注意

- `tools/runops/` に未コミットの変更がある場合は pull 前にコミットまたは stash する
- local patch の正本は `tools/runops` 内の Git branch / commit とする。
  別枠の mutable patch 履歴はデフォルトでは作らない
- `update-harness` で `.new` ファイルが生成されたら、差分を確認してから元ファイルに反映する
- 更新後は `runo doctor` で環境が正常か確認するとよい
