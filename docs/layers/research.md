# Research Layer

Research Layer は active research memory を量で制限し、AI の重要度推測に依存せず
長期再開可能にする層です。

```text
research/
  CURRENT.md
  journal/active.md
  journal/archive/JNNNN.md
  results/RNNNN-topic/{README.md,manifest.toml,artifacts/}
  archive/results/
.runops/work/<goal-id>/
```

`CURRENT.md` は現在の問い、判断、次の一手だけを置く入口です。journal は append-only
で、日数ではなく文字数により原文のまま rotation します。`--kind` / `--subject` で
Experiment / Survey / Run と結び付けられます。結果は人が残すと決めたものだけ
`results/` に昇格し、説明を README 1 枚へ集約します。

`CURRENT.md` は既定 50 行を目安にし、path 参照 10 件、日付・時刻で始まる見出し 3 件を
越えると warning を出します。これは通常作業を止める hard gate ではありません。
時系列は `runo research append`、残す詳細解析は `results/`、網羅的な artifact provenance は
export/source index に置き、`CURRENT.md` を日誌や inventory に戻さないでください。

```bash
runo research status
runo research append "<title>" "<body>"
runo research new-result <topic>
runo research seal R0001-topic --claim "..." --outcome supported \
  --selection-reason "Why this source supports the claim" \
  --evidence-run R2026...
runo research check-result R0001-topic
runo research archive R0001-topic
runo research check
```

Result は evidence の include / exclude 判断を local edge として所有します。Run の review
status は「結果を確認したか」であり、「どの claim に採用したか」ではありません。
T ID と `.runops/test-runs/**` は scientific evidence にできません。seal は README と source
receipt を固定し、後からの変化を `check-result` で検出します。

included Run / Run-owned artifact を seal するには、owner Run が completed 相当かつ理由付き
review 済みで、identity hashes、source commit、executable hash、simulator version、baseline、
input snapshot を備えている必要があります。dirty source は diff 参照も必要です。review は
source quality gate であって、claim への採否は引き続き Result が決めます。
Run-owned path の owner は canonical Run namespace の外側の正式 Run rootで決まり、payload
内部の `manifest.toml` は別Runへのowner差し替えには使いません。
sealed Result が Run の `work/outputs`、`work/restart`、`work/tmp` 配下を include した場合、
`runo runs purge-work` は reverse reference を検出して削除を拒否します。この検出では
seal の content hash と README/evidence receipt も再検証するため、include を exclude へ
書き換えるなど sealed Result に改竄があれば fail closed で purge を止めます。

`artifacts/` に Markdown を置かず、同じ論理データの形式違いコピーを避けます。
AI は既存 evidence を削除または要約置換しません。archive は可逆で、purge はありません。

case / survey root の `notes.md` と Run `analysis/notes.md` は narrative の増殖を招くため legacy
slot とし、lint warning の対象です。途中の prose は `.runops/work/`、時系列は journal、
current decision は CURRENT、durable narrative は Result README へ集約します。

旧構成は `runo research migrate-legacy --dry-run` で移動一覧を確認してから適用し、
必要なら `--restore` で戻します。
