---
name: check-status
description: Check and sync run or survey status. Use when monitoring job progress or after submission.
---

# Run / Survey の状態を確認・同期する

```bash
# プロジェクト全体の active jobs
runo runs jobs

# 特定ディレクトリの run 一覧
runo runs list $ARGUMENTS

# 個別 run の同期と確認
cd <run_dir>
runo runs sync
runo runs status
```

## survey 全体のステータスを確認する場合

```bash
runo runs sync $ARGUMENTS
runo runs list $ARGUMENTS
runo runs jobs
```

状態をサマリーとして報告する: completed / running / failed / submitted の数。
`sync` を先に走らせて Slurm 上の最新状態を manifest に反映してから一覧する。

## ハング検出 (running run の runtime health check)

Slurm の state が RUNNING のままでも、シミュレーションが HDF5 deadlock などで
hang していることがある。以下を各 running run で確認する:

1. `work/stdout.*.log` の最終更新時刻 (mtime) と現在時刻の差
2. 最終 `step -------- N` と `nstep` の比から進捗 %
3. mtime が閾値 (例: 30 分) を超えていたら **ハング候補** として警告

```bash
# 最新 stdout と mtime を確認する一例
latest=$(ls -t <run>/work/stdout.*.log 2>/dev/null | head -1)
if [ -n "$latest" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$latest") ))
  step=$(grep -o 'step *-*[0-9]\+' "$latest" | tail -1)
  echo "$run: $step, stdout updated ${age}s ago"
fi
```

報告フォーマット例:

```
R20260413-0004: step 389079/400000 (97%), stdout updated 3s ago OK
R20260413-0001: step 200000/400000 (50%), stdout updated 71h ago HANG?
```

