---
name: hops-export-feedback
description: サニタイズ済みのプロジェクト側フィードバックをターゲットハーネスまたは HarnessOps へエクスポートするときに使う。
---

`hops doctor --check-overlay` を実行し、続けて `hops feedback export --target <target> --sanitize` を使う。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。リモートIssueやプルリクエストは作成しない。

送信元プロジェクト外へ共有する前に、エクスポートされたバンドルにローカルパス、非公開語、未公開研究の詳細が残っていないか確認する。
