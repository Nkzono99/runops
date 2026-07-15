---
name: research-workspace
description: Keep project research memory bounded by character and artifact budgets; append or rotate the journal, promote durable results, and archive results without deleting evidence.
---

# Research workspace を整理する

研究記憶の正本は `research/` の次の 3 層だけにする。

- `CURRENT.md`: 現在の問い、判断、次の一手。過程の全文は置かない
- `journal/`: append-only な作業記録。量の上限で segment を無要約ローテーションする
- `results/RNNNN-topic/`: 残す解析結果。説明は `README.md` 1 枚、実体は `artifacts/`

途中生成物は `.runops/work/<goal-id>/` に置く。ここを durable result とみなさない。

## 手順

1. `runo research status` を実行し、文字数・件数・bytes と警告を確認する。
2. 作業経緯は `runo research append "<title>" "<body>"` で追記する。
3. journal が上限に達したら CLI の自動 rotation に任せる。手動なら `runo research rotate --force`。
4. 再利用・再検証する価値が確定したものだけ `runo research new-result <topic>` で昇格する。
5. result の結論、根拠、限界、再現手順、artifact index は 1 枚の `README.md` に集約する。
6. `artifacts/` に Markdown を作らない。同じ論理データの CSV/JSON/Markdown 重複を避ける。
7. active result が増えたら `runo research archive RNNNN` で可逆 archive する。削除しない。
8. 最後に `runo research check` を通す。

AI が重要度を推測して既存 evidence を削除・要約置換してはいけない。重要性の判断が
必要なら、原文を保ったまま result 候補と理由を人に示す。
