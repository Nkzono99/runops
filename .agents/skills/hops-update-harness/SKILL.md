---
name: hops-update-harness
description: HarnessOps にリンク済みのリポジトリを、現在の hops 実装に合わせて更新または検証するときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。更新は `uvx --refresh-package harnessops --from harnessops hops update-harness` に委譲します。
事前確認だけをしたい場合は `uvx --from harnessops hops doctor --check-overlay --check-records` を使います。
lock に記録された `harnessops_version` が古い場合、通常の `update-harness` は PyPI 上の checkpoint 版を uvx で順に適用してから現在版の更新を続けます。更新チェーンだけを確認したい場合は `--plan-upgrade` を使います。

基本手順:

1. `.harnessops/project.toml` を読み、profile と overlay path を確認する。
2. まず現在状態を検証する。

```bash
uvx --refresh-package harnessops --from harnessops hops update-harness
```

3. 古い repo で段階更新の中身を先に確認する場合:

```bash
uvx --refresh-package harnessops --from harnessops hops update-harness --plan-upgrade
```

4. repo-local HarnessOps skills を明示的に入れる、または再展開する場合:

```bash
uvx --refresh-package harnessops --from harnessops hops update-harness --agent-bridge --codex
```

5. 未適用 migration を適用する場合は、人間の指示または target CLI 側の明示フラグがあるときだけ実行する。

```bash
uvx --refresh-package harnessops --from harnessops hops update-harness --apply-migrations
```

6. update-harness 自体の自動 chain ではなく、exact version の subprocess 列だけを明示的に実行する場合:

```bash
uvx --refresh-package harnessops --from harnessops hops update-harness --apply-upgrade-chain
```

target CLI の `update-harness` から呼ぶ場合も、target CLI は HarnessOps 管理ファイルを直接書かず、この uvx 導線を subprocess として呼ぶ。

編集済みの HarnessOps managed file は上書きされず、runops と同様に `<path>.new` が作られます。差分を確認して手動で取り込むか、明示的に `--force` を使います。
