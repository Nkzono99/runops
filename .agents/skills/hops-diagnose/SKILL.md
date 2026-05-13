---
name: hops-diagnose
description: リポジトリが HarnessOps にリンクされているか、オーバーレイが健全かを確認するときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

`hops doctor --check-overlay` を実行する。リポジトリがリンクされていなければ、`uvx --from harnessops hops detect` を実行して `uvx --from harnessops hops init --profile <detected-profile>` を提案する。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。
