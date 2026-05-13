---
name: update-runops
description: Update the uvx-run runops tool path and refresh project harness files. Use when runops has a new release, harness templates need updating, or CLI notices report a version mismatch.
---

# runops を更新する

通常の project では runops 本体の source checkout を `tools/runops/` に持たない。
runops CLI は `uvx --from runops runo ...` を標準経路にし、project `.venv` は
simulator package、解析依存、runtime tool 用に使う。

## 1. runops tool version を確認

```bash
uvx --from runops runo --version
```

特定 version に固定したい場合:

```bash
uvx --from "runops==<version>" runo --version
```

offline / pinned workflow で runops CLI を project `.venv` に常駐させる必要が
ある場合だけ、明示的に install する:

```bash
uv pip install "runops==<version>" --python .venv/bin/python
```

通常は `.venv` の runops を更新しない。

runops 本体に local patch が必要な場合は、project の外に source checkout を用意し、
`{{ skill_prefix }}patch-runops` で branch / commit / upstream disposition を整理する。

## 2. versioned harness upgrade chain を確認・適用

```bash
uvx --from runops runo update-harness --plan
uvx --from runops runo update-harness --apply-chain
```

- `--plan` は `.runops/harness.lock` の最後に適用した runops version から、
  target までの checkpoint chain を表示する
- `--apply-chain` は各 checkpoint を `uvx --from runops==<version>` で呼び替えて
  `update-harness --upgrade-step` を順に実行する
- 未編集のファイルは自動で上書きされる
- ユーザーが編集済みのファイルは `<path>.new` として出力されるので diff を確認してマージする
- `.vscode/settings.json` もこの更新対象に含まれる
- `notes/`, `materials/`, `research/` は不足している scaffold だけ補完される
- `.runops/knowledge/runops/agent-user-guide.md` と `imports.md` も実行中の runops package から再生成される
- `.runops/harness.lock` に最後に適用した runops version が記録される
- `.runops/harness.lock` の `upgrade_chain` に exact-version step の履歴が記録される
- `--dry-run` で事前確認、`--force` で全上書き
- HarnessOps overlay がある場合は `hops update-harness` も連鎖し、repo-local HarnessOps skills と overlay metadata を更新する

## 3. migration guide を確認

まず generated guide と CLI を入口にする。harness chain は自動で踏むが、
project-state migration は別物なので、runner の結果と migration guide を確認する。

```bash
uvx --from runops runo migrate list
uvx --from runops runo migrate show <id>
uvx --from runops runo migrate apply <id> --dry-run
```

runops v0 系では後方互換性を強く維持しない。project 側の状態に影響する変更は
release note または migration guide に migration item として書かれている前提で扱う。

確認すること:

- target runops version に対応する migration item を読む
- current project に該当する migration item があるか判定する
- 登録済みの定型 migration は `runo migrate apply <id> --dry-run` で確認し、
  問題なければ `runo migrate apply <id>` で適用する
- `compatible-generated` は scope を説明してから適用する
- `manual-edit` / `breaking-manual` / `destructive-human-gate` は
  `{{ skill_prefix }}migrate-runops` に渡す
- guide にない破壊的変更や schema rewrite は推測で実行しない。
  足りない場合は `{{ skill_prefix }}feedback-runops` の HarnessOps feedback 候補にする

Migration を適用 / skip / defer した場合は、`notes/YYYY-MM-DD.md` に記録する。

## 4. シミュレータパッケージを更新

```bash
uvx --from runops runo update
```

`runo update` は adapter が宣言する package spec に合わせて simulator package を更新する。
`refs/<simulator>/` を editable install して simulator 本体を開発している場合は、
更新前に warning と確認が出る。

- git-pinned / package install が通常運用。再現性と provenance を優先する
- editable install は simulator 本体を修正・debug するときだけの opt-in
- editable を package spec に戻してよい場合だけ `runo update --yes` または
  `runo update --force` を使う

## 一括実行

```bash
uvx --from runops runo update-harness --plan
uvx --from runops runo update-harness --apply-chain
uvx --from runops runo migrate list
uvx --from runops runo update
```

一括実行後も migration guide の確認は省略しない。

## 注意

- `update-harness` は runops source checkout を pull しない。現在 `uvx` で実行中の package が正本。
- `.runops/harness.lock` の `runops_version` が実行中 version より古い場合は、
  `uvx --from runops runo update-harness --plan` で chain を確認してから
  `--apply-chain` を実行する。
- `.runops/harness.lock` の `runops_version` が実行中 version より新しい場合は、
  stale な project `.venv` の `runo` を踏んでいる可能性があるため、`uvx --from runops runo ...` を使う。
- local patch の正本は別 checkout 内の Git branch / commit とする。
- `update-harness` で `.new` ファイルが生成されたら、差分を確認してから元ファイルに反映する。
- migration item がある場合は `{{ skill_prefix }}migrate-runops` で扱う。
- 更新後は `uvx --from runops runo doctor` と `uvx --from runops runo lint` で環境と project state を確認するとよい。
