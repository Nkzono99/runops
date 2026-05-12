---
name: hops-update-harness
description: HarnessOps にリンク済みのリポジトリを、現在の hops 実装に合わせて更新または検証するときに使う。
---

`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。更新は `hops update-harness` に委譲します。
事前確認だけをしたい場合は `hops doctor --check-overlay --check-records` を使います。

基本手順:

1. `.harnessops/project.toml` を読み、profile と overlay path を確認する。
2. まず現在状態を検証する。

```bash
hops update-harness
```

3. repo-local HarnessOps skills を明示的に入れる、または再展開する場合:

```bash
hops update-harness --agent-bridge --codex
```

4. 未適用 migration を適用する場合は、人間の指示または target CLI 側の明示フラグがあるときだけ実行する。

```bash
hops update-harness --apply-migrations
```

target CLI の `update-harness` から呼ぶ場合も、target CLI は HarnessOps 管理ファイルを直接書かず、このコマンドを subprocess として呼ぶ。

編集済みの HarnessOps managed file は上書きされず、runops と同様に `<path>.new` が作られます。差分を確認して手動で取り込むか、明示的に `--force` を使います。
