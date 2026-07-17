---
name: patch-runops
description: Use when the requested outcome is an isolated, verified runops fix and an explicit upstream disposition.
---

# projectと分離してrunops本体を直す

## 実行契約

- **Goal**: projectで見つかったrunopsのbug /不足機能 / harness摩擦を別checkoutで修正する
- **Done**: source commit、対象test、projectでの確認結果、upstream dispositionを報告できる
- **Budget**: 一つのissueと関連source / targeted testsだけ
- **Invariant**: 研究projectとsource変更を混ぜず、dirty worktreeとprivate research dataを保護する

## Ownership routing

| change | owner |
|---|---|
| project固有の研究判断・data・site秘密 | current project |
| project固有harness override | current project |
| 汎用CLI / core / adapter / launcher | separate runops checkout |
| 汎用project scaffold / harness | checkoutの`src/runops/templates/` |

生成済み`.agents/skills/`、`.claude/skills/`、`AGENTS.md`、`CLAUDE.md`や
`research/`、`campaign.toml`、`cases/`、`runs/`をそのままupstreamへコピーしない。

## Patch route

```bash
git clone https://github.com/Nkzono99/runops.git ../runops-src
git -C ../runops-src status --short
git -C ../runops-src switch -c fix/<short-name>
```

既存checkoutがあれば再利用し、未コミット変更を壊さない。修正はrunops開発ハーネスに従い、
targeted test、Ruff、必要なtype checkを通してlogical commitにする。current projectでの確認が
Doneに必要な場合だけ、そのcheckoutを一時installする。

| disposition | condition |
|---|---|
| `local-only` | project固有でupstream化しない |
| `feedback-issue` | 汎用性または設計が未確定 |
| `draft-pr` | 実装案はあるがreviewが必要 |
| `ready-pr` | 小さく汎用で検証済み |

issue / PR / pushは依頼されたexternal outcomeに含まれる場合だけ行い、project固有path、
未公開result、credentialを除く。研究記録が必要ならcommitとdispositionだけを別Goalで残す。
