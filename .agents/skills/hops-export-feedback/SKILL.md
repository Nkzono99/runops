---
name: hops-export-feedback
description: サニタイズ済みのプロジェクト側フィードバックをターゲットハーネスまたは HarnessOps へエクスポートするときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

`hops doctor --check-overlay` を実行し、続けて `hops feedback export --target <target> --sanitize` を使う。公開GitHub Issue用の下書きが必要な場合は `--format github-issue` を付け、`hops feedback issue create <bundle> --repo <owner/repo>` で title/body と重複候補を確認する。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。リモートIssueは `--confirm-create` が明示された場合だけ作成し、プルリクエストは作成しない。

送信元プロジェクト外へ共有する前に、エクスポートされたバンドルにローカルパス、非公開語、未公開研究の詳細が残っていないか確認する。
