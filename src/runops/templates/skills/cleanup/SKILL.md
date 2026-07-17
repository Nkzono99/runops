---
name: cleanup
description: Use when the user explicitly requests archive, cancel, purge, or deletion for identified runs.
---

# 指定runをrequested lifecycle stateへ移す

## 実行契約

- **Goal**: 指定runをarchived / cancelled / purged / deletedの要求状態へ移す
- **Done**: 対象、実行command、結果state、保持・削除したevidenceを報告できる
- **Budget**: 明示されたrun集合と一つのlifecycle transition

## Plan

```bash
runo runs list $ARGUMENTS
```

| requested state | entry | command |
|---|---|---|
| `archived` | completed | `runo runs archive` |
| `archived` in place | completed | `runo runs archive --keep-in-place` |
| work purged | archived | `runo runs purge-work` |
| incomplete work purged | archived + discard判断 | `runo runs purge-work --discard-incomplete --reason "<理由>"` |
| `cancelled` | submitted / running | `runo runs cancel` |
| directory deleted | created / cancelled / failed | `runo runs delete` |

## Checkpoint

- archive / purge / deleteは対象、移動先、削除範囲、evidence readinessを示して承認を得る
- cancelは対象と理由を報告して実行する
- completed evidenceを縮小するGoalはarchive → purgeのstate順序を使う

承認された一遷移を実行し、更新stateと残存artifactを確認してDoneを返す。
