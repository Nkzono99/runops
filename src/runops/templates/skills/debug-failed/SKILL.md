---
name: debug-failed
description: Diagnose failed runs and propose fixes. Use when a run has failed and needs investigation.
---

# 失敗した Run を診断する

```bash
cd $ARGUMENTS
runo runs sync
runo runs status
runo runs log -e
runo runs log
```

必要なら `work/` 以下も確認:

```bash
ls work/
tail -n 100 work/*.err
tail -n 100 work/*.out
```

## 判断の目安

| failure_reason | 対処 |
|---|---|
| `timeout` | walltime 延長候補 |
| `oom` | メモリ増加または問題サイズ縮小 |
| `preempted` | 同条件再投入 |
| `exit_error` | log / err を確認してから判断 |

## retry の進め方

- case.toml または survey.toml を修正して新しい run を生成する
- 同じ run の試行回数が 3 回前後に達したら、自動 retry を止めて原因を要約する


