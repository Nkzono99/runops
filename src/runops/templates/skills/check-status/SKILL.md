---
name: check-status
description: Check and sync run or survey status only when the user explicitly asks for status, monitoring, logs, or a bounded post-submit startup check. Do not auto-invoke after submission.
---

# Run / Survey の状態を確認・同期する

通常の submit 完了だけでは自動発火しない。submit 後は job_id を報告して返し、
自動で待機・sync・log 確認を始めない。

```bash
# プロジェクト全体の active jobs
runo runs jobs

# 特定ディレクトリの run 一覧 (cached analysis / next action を含む)
runo runs list $ARGUMENTS

# 個別 run の同期と確認
cd <run_dir>
runo runs sync
```

`sync` が terminal transition を検出した場合、analysis readiness、reason code、
recommended action / exact command も同時に返す。必要な情報が揃っていれば定型的な
`status` 再実行は省き、返された command へ直接進む。cache が無い既存 terminal run や
追加詳細が必要な場合だけ `runo runs status` を使う。

## survey 全体のステータスを確認する場合

```bash
runo runs sync $ARGUMENTS
runo runs jobs
```

sync summary と recommended command で判断できない場合だけ `runo runs list $ARGUMENTS`
を追加する。`runs list` と `runs dashboard --all` は cache-only なので、一覧中に各 run の
deep evaluation は起動しない。`ANALYSIS=unknown`, `NEXT=deep_validate` の run だけ
`runo runs status <RUN_ID>` へ進む。

状態をサマリーとして報告する: completed / running / failed / submitted の数。
`sync` を先に走らせて Slurm 上の最新状態を manifest に反映してから一覧する。

## Startup check (明示依頼時のみ)

ユーザーが「正常に動いているか数 step 見て」「初動確認して」「log を確認して」
「監視して」と明示的に startup check を依頼した場合だけ行う。
「smoke run を投入して」だけでは startup check まで含めない。

1. 対象 run、成功条件、待機期限を先に示す
2. `runo runs sync <RUN>` で Slurm state を確認する
3. RUNNING になったら `runo runs log <RUN> -n 50` で progress marker / step を読む
4. 必要なら bounded interval でもう一度だけ確認し、step が進んだかを見る
5. progress を確認できた時点または期限に達した時点で終了して報告する

期限の指定がなければ短い startup window に留める。PENDING が続く場合や出力がまだ
無い場合は、その状態を報告して返す。`runo runs log -f`、無期限 loop、job 完了までの
待機には進まない。

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
