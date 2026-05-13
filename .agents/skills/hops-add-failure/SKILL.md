---
name: hops-add-failure
description: プロジェクト失敗、ハーネス摩擦、ローカル回避策、上流フィードバック候補を HarnessOps 経由で記録するときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

HarnessOps を使う。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。

1. `hops doctor --check-overlay` を実行する。
2. リポジトリがリンクされていなければ、`uvx --from harnessops hops detect` を実行して `uvx --from harnessops hops init --profile <id>` を提案する。
3. 起きたこと、悪影響、望ましい挙動、プライバシーリスクの文脈を集める。
4. `hops add-failure --interactive` を実行するか、下書きコマンドを作る。
5. disposition が不明確なら `hops route --record <id>` を実行する。
6. 上流/メタ候補なら `hops feedback export --target <target> --sanitize` を提案する。

プロジェクト発展は `research/` または `notes/` に残す。非公開研究の詳細、生パス、未公開語を上流フィードバックへ移さない。
