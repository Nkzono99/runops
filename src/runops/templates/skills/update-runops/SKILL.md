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

## 3. migration guide を確認

```bash
sed -n '1,220p' tools/runops/docs/migrations/README.md
sed -n '1,260p' tools/runops/docs/migrations/v0.md
```

runops v0 系では後方互換性を強く維持しない。project 側の状態に影響する変更は
`docs/migrations/` に migration item として書かれている前提で扱う。

確認すること:

- target runops version に対応する `docs/migrations/v<major>.md` を読む
- current project に該当する migration item があるか判定する
- `compatible-generated` は scope を説明してから適用する
- `manual-edit` / `breaking-manual` / `destructive-human-gate` は
  `{{ skill_prefix }}migrate-runops` に渡す
- guide にない破壊的変更や schema rewrite は推測で実行しない。
  足りない場合は `{{ skill_prefix }}feedback-runops` 候補にする

Migration を適用 / skip / defer した場合は、`notes/YYYY-MM-DD.md` に記録する。

## 4. シミュレータパッケージを更新

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
ただし、一括実行後も migration guide の確認は省略しない。

## 注意

- `tools/runops/` に未コミットの変更がある場合は pull 前にコミットまたは stash する
- local patch の正本は `tools/runops` 内の Git branch / commit とする。
  別枠の mutable patch 履歴はデフォルトでは作らない
- `update-harness` で `.new` ファイルが生成されたら、差分を確認してから元ファイルに反映する
- `docs/migrations/` に該当 item がある場合は `{{ skill_prefix }}migrate-runops` で扱う
- 更新後は `runo doctor` で環境が正常か確認するとよい
