---
name: update-runops
description: Update runops itself and refresh harness files. Use when runops has a new release or harness templates need updating.
---

# runops を最新版に更新する

## 1. tools/runops を pull

```bash
cd tools/runops && git pull && cd -
```

pull が失敗した場合 (diverge 等):

```bash
cd tools/runops && git fetch origin && git reset --hard origin/main && cd -
```

## 2. ハーネスファイルを再生成

```bash
runo update-harness
```

- 未編集のファイルは自動で上書きされる
- ユーザーが編集済みのファイルは `<path>.new` として出力される → diff を確認してマージ
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
- `update-harness` で `.new` ファイルが生成されたら、差分を確認してから元ファイルに反映する
- 更新後は `runo doctor` で環境が正常か確認するとよい
