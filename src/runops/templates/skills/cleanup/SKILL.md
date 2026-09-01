---
name: cleanup
description: Use when the user explicitly requests restore, archive, cancel, purge, or deletion for identified runs.
---

# 指定runをrequested lifecycle stateへ移す

## 実行契約

- **Goal**: 指定runをcompletedへ復元、またはarchived / cancelled / purged / deletedの要求状態へ移す
- **Done**: 対象、実行command、結果state、保持・削除したevidenceを報告できる
- **Budget**: 明示されたrun集合と一つのlifecycle transition
- **Invariant**: canonical runops commandとhuman checkpointを使い、対象外のrunやevidenceに触れない

## Plan

```bash
runo runs list --include-archived $ARGUMENTS
```

| requested state | entry | command |
|---|---|---|
| `archived` | completed | `runo runs archive` |
| `archived` in place | completed | `runo runs archive --keep-in-place` |
| `completed`へ復元 | archived | `runo runs restore` |
| work purged | archived | `runo runs purge-work` |
| incomplete work purged | archived + discard判断 | `runo runs purge-work --discard-incomplete --reason "<理由>"` |
| `cancelled` | submitted / running | `runo runs cancel` |
| directory deleted | created / cancelled / failed | `runo runs delete` |
| old TestAttempt deleted | terminal `passed|failed|skipped` + age cutoff | `runo test clean --older-than-days N` |

## Checkpoint

- archive / purge / deleteは対象、移動先、削除範囲、evidence readinessを示して承認を得る
- restoreは元のpathが空いていることを確認し、artifactを保持したまま実行する
- cancelは対象と理由を報告して実行する
- completed evidenceを縮小するGoalはarchive → purgeのstate順序を使う
- sealed ResultがincludeしたRun-owned path evidenceはpurgeせず、Result側へcopyしてresealするか保護を維持する
- retention `review_after` / `expire_after`だけを削除権限にしない
- archive / restore / purge後はlifecycleと独立なstorage metadataも確認する:
  archive=`cold`, restore=`hot`, purge=`cold/compacted`
- TestAttempt cleanupは古いactive attemptが一件でもあれば全体を拒否する
- `runo triage`のstaging診断は自動削除権限ではなく、24時間以上残った候補を目視確認する入口とする

承認された一遷移を実行し、更新stateと残存artifactを確認してDoneを返す。
