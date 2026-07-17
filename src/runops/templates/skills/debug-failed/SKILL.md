---
name: debug-failed
description: Use when the requested outcome is an evidence-backed cause and next action for one or more failed runs.
---

# failed runの原因をevidenceから特定する

## 実行契約

- **Goal**: failed runを分類し、修正・retry・deferの判断材料を作る
- **Done**: failure reason、根拠log、影響する設定、推奨next actionを報告できる
- **Budget**: 指定runだけ。sync / statusは各1回、logは原因gapを解消する範囲に限定する
- **Invariant**: 既存runのmanifestとwork evidenceを変更せず、retryを自動実行しない

## Evidence routing

```bash
runo runs sync <run>
runo runs status <run>
runo runs log <run> -e
runo runs log <run> -n 100
```

statusの`failure_reason`とreason codeを入口にし、必要な場合だけ`work/`の対応する
stderr / stdout末尾を読む。directory全体や無関係なrunを走査しない。

| failure reason | 判断候補 |
|---|---|
| `timeout` | walltime、進捗率、checkpoint有無から延長可否を判断 |
| `oom` | peak memory evidenceと問題サイズから資源増加か縮小を判断 |
| `preempted` | input変更なしのretry候補 |
| `exit_error` | 最初のactionable errorとsimulator固有診断へroute |

再利用する修正はcase / surveyへ戻して新しいrunを生成する。同条件retryを提案する場合も、
試行履歴と上限を示す。3回前後の反復失敗は原因要約をDoneとして返し、追加retryを止める。
