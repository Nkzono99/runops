---
name: harnessops-bridge
description: プロジェクト失敗の記録、上流フィードバックのルーティング、HarnessOps 改善ワークフローの実行時に使う。
---

このリポジトリは HarnessOps にリンクされています。

ハーネス状態の正本は `hops` CLI です。まず `.harnessops/project.toml` を読み、profile、overlay mode、overlay path を確認してください。
下流の target/project repo では PATH 上の `hops` に依存せず、原則 `uvx --from harnessops hops <command>` を使います。

`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えないでください。レコード作成、ルーティング、エクスポート/インポート、ラボ評価、採用判断は CLI に委譲します。

- `uvx --from harnessops hops doctor --check-overlay`
- `uvx --from harnessops hops feedback import <bundle-path>`
- `uvx --from harnessops hops lab capture --title <title> --summary <summary> --expected-change <expected>`
- `uvx --from harnessops hops lab dossier --from <FBid>`
- `uvx --from harnessops hops lab investigate --from <IMPid> --summary <summary>`
- `uvx --from harnessops hops lab classify --from <IMPid>`
- `uvx --from harnessops hops lab new-eval-case --from <FBid>`
- `uvx --from harnessops hops propose --from <Eid>`
- `uvx --from harnessops hops eval --case <Eid> --manual`
- `uvx --from harnessops hops decide --from <id> --status <status>`
- `uvx --refresh-package harnessops --from harnessops hops update-harness`
- `uvx --refresh-package harnessops --from harnessops hops update-harness --plan-upgrade`
- `uvx --from harnessops hops migrate --check`

外部共有前にサニタイズ済みバンドルを確認し、ローカルパス、非公開語、未公開研究の文脈を残さないでください。
