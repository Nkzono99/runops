---
name: hops-github-flow
description: target/meta HarnessOps repo で GitHub Flow の preflight、branch push、PR 作成、required checks 後の merge を HOPS CLI に委譲するときに使う。project repo では通常使わない。
---

Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

この skill は target/meta repo の GitHub Flow を標準化する入口です。`.harnessops/project.toml` の `[github_flow] enabled = true` かつ overlay mode が `upstream-lab` / `meta-lab` の repo だけで使います。project repo では `harness-feedback/` を積み上げる運用を優先し、通常この flow は配布されません。

`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。HarnessOps の状態変更は `hops` CLI に委譲します。

## 基本手順

1. repo 設定と clean state を確認する。

```bash
uvx --from harnessops hops github-flow preflight --pull
```

2. 実装、skill/docs 変更、`hops lab ...` など必要な local advance を行う。

3. 検証する。

```bash
uvx --from harnessops hops doctor --check-overlay --check-records
```

4. 検証が通ったら branch commit と push を HOPS に委譲する。

```bash
uvx --from harnessops hops github-flow publish --branch codex/<topic> --message "<summary>" --validation-passed
```

5. PR を作る。issue を閉じる場合は `--close-issue <number>` を付ける。

```bash
uvx --from harnessops hops github-flow pr --title "<title>" --body "<summary>" --close-issue 12
```

6. required checks が通り、conflict がなければ merge する。

```bash
uvx --from harnessops hops github-flow merge --require-checks
```

## 判断基準

- target/meta repo では、push、PR、merge、issue close を hand-roll せず `hops github-flow ...` を優先する。
- project repo ではこの flow を使わない。project 側の観測は `harness-feedback/` に記録し、必要に応じて target/meta repo に export/import する。
- `[github_flow] enabled = false` の repo ではこの skill を使わず、`hops update-harness --agent-bridge --no-github-flow` で配布対象から外す。
- `publish` は validation 済みの変更だけに使う。validation なしで commit/push が必要な場合は、人間の明示指示を確認する。
- merge 前に required checks と conflict 状態を確認する。失敗時は merge せず、原因を報告する。

## 出力

短く報告する。

- branch / PR / merge 状態
- 実行した `hops github-flow ...` command
- validation 結果
- blocked reason
- 次に必要な人間判断
