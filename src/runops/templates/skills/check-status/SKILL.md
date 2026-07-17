---
name: check-status
description: Use when the requested outcome requires current job state, progress evidence, log inspection, or bounded startup validation.
---

# Run / Survey の状態と進行 evidence を得る

## 実行契約

- **Goal**: ユーザーが求める時点の state または progress evidence を得る
- **Done**: 状態要約、進行を示す evidence、推奨する次アクションを報告できる
- **観測予算**: 通常は sync 1 回。startup check は progress snapshot 2 回以内、または指定期限まで

依頼が state summary なら state の同期で完了する。依頼が startup validation を含むなら、
指定した step / progress marker の変化を Done に加える。

## 状態確認

```bash
# project 全体の active jobs
runo runs jobs

# 個別または survey の状態を Slurm と同期
runo runs sync $ARGUMENTS
```

`sync` が返す state、analysis readiness、reason code、recommended command を evidence に使う。
追加の run detail が Done に必要なときは `runo runs status <RUN_ID>`、survey の内訳が
必要なときは `runo runs list $ARGUMENTS` を加える。

survey は completed / running / failed / submitted の件数と、次に扱う run をまとめて報告する。
cache 上で `ANALYSIS=unknown`, `NEXT=deep_validate` の run は、その run_id に対して
`runo runs status` を実行する。

## Startup check

ユーザーの Done に「正常に動いている」「数 step 進んだ」などの初動 evidence が含まれる
場合に使う。

1. 対象 run、progress marker、観測期限を決める
2. `runo runs sync <RUN>` で Slurm state を得る
3. RUNNING なら `runo runs log <RUN> -n 50` で最初の snapshot を得る
4. progress の変化が必要なら、観測予算内でもう一つ snapshot を得る
5. progress evidence、または期限時点の PENDING / RUNNING / output 未生成状態を報告する

期限指定がない startup check の観測予算は短い window と snapshot 2 回以内を採用する。
job 完了までの観測は、それを Goal とする依頼として別の予算を設定する。

## Runtime health evidence

hang 診断が Goal に含まれるときは、running run ごとに stdout の最終更新時刻、最終 step、
`nstep` に対する進捗率を読む。更新間隔が simulator の想定を超えた run を hang 候補として、
観測値と閾値を添えて報告する。
