---
name: hops-import-feedback
description: サニタイズ済みフィードバックバンドルを harness-lab にインポートするときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

`hops doctor --check-overlay` を実行し、続けて `hops feedback import <bundle-path>` を使う。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。インポート済みフィードバックは、採用判断の前に評価ケースへ変換する。
