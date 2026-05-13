---
name: hops-route-feedback
description: HarnessOps フィードバックを project、target、meta、protocol、external、private のdispositionへ分類するときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

`hops doctor --check-overlay` を実行し、続けて `hops route --record <id>` を使う。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。プロジェクト発展は `harness-feedback/` ではなく `research/` または `notes/` に置く。

1つのイベントにプロジェクト判断とハーネス不足の両方が含まれる場合は、1つのdispositionへ押し込まず、プロジェクトレコードと上流/メタフィードバックに分割する。
