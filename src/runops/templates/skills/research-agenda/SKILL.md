---
name: research-agenda
description: Update the project-level research agenda. Read campaign.toml, recent notes, reports, run status, and research/agenda.md; then update the current decision state, active questions, next actions, paused/killed directions, and feedback candidates.
---

# Research agenda を更新する

この skill は `research/agenda.md` を更新する。目的は、次の Agent / 人間が
同じ研究判断の地点から再開できるようにすること。

`research/agenda.md` は TODO リストではなく、**判断の台帳** である。
**agenda.md is not an artifact ledger.**
Do not put chronological notes or artifact inventories back into agenda.md.
本文は日本語で書き、コード、コマンド、変数名、run_id、ファイルパス、
エラーメッセージは実際の表記のまま残す。

## 役割

- `research/agenda.md` は mutable な現在状態。
- `notes/YYYY-MM-DD.md` は append-only な時系列ログ。
- `notes/reports/README.md` は report 群の reading order / entry point。
- `notes/reports/` は改稿可能な整理済み report。
- `analysis/cross_run/<comparison_id>/` は複数 run 比較の data / figures /
  scripts / logs などの機械的 artifact。
- `.agents/skills/` / `.claude/skills/` は手順であり、研究状態ではない。
- `research/proposals/` と `research/reviews/` は必要時のみ使う。

## 入力として読むもの

必要な範囲で読む:

- `campaign.toml`
- `research/agenda.md`
- latest `notes/YYYY-MM-DD.md`
- relevant `notes/reports/*.md`
- relevant run manifests / summaries / figures
- `.runops/facts.toml` / `.runops/insights/` if relevant

## 更新する項目

`research/agenda.md` に以下を反映する:

1. Charter / 研究憲章
   - 研究の北極星 (North star)
   - 対象外 (Out of scope)
   - 既知の交絡要因 (Known confounds)

2. Current Beliefs / 現在の見立て
   - 主張 (claim)
   - 根拠 path (evidence path)
   - 確信度 (confidence)
   - 留保 (caveat)

3. Active Questions / 現在の問い
   - 問い (question)
   - なぜ重要か (why it matters)
   - 現在の根拠 (current evidence)
   - 足りない根拠 (missing evidence)
   - 次に必要な判断 (next decision needed)

4. Current Decision / 現在の判断
   - 判断 (decision)
   - 理由 (rationale)
   - 根拠 (evidence)
   - 検討した代替案 (alternatives considered)
   - 代替案を採らない理由 (why not alternatives)

5. What Would Change Our Mind / 判断が変わる条件
   - observations that would strengthen/weaken/kill the current direction

6. Next Actions / 次の行動
   - 具体的な行動 (exact action)
   - なぜ今 (why now)
   - 期待する出力 (expected output)
   - 成功/失敗基準 (success/failure criterion)
   - 作る根拠 path (evidence path to produce)
   - human gate yes/no

7. Paused / Killed / 保留・終了した方向
   - 状態 (status)
   - 理由 (reason)
   - 再検討条件 (revisit condition)

8. Feedback To runops / runops 本体へのフィードバック候補
   - only repeated workflow friction, missing commands, docs gaps, bugs, or
     upstream improvements

## proposal / review を作る条件

普段は `agenda.md` だけを更新する。次の場合は、実行前に
`research/proposals/<date>-<topic>.md` を作る:

- production sweep
- new physical model family
- high-cost rerun
- campaign-level assumption の変更
- report / paper レベルの claim

次の場合は、実行後または checkpoint として
`research/reviews/<date>-<topic>.md` を作る:

- major result
- failed or surprising run
- three or more related note entries
- pivot / pause / kill decision

## 重要ルール

- `agenda.md` を TODO リストにしない。
- evidence path なしに判断を書かない。
- model 名だけで議論しない。
- 新しい production run / new model family / large sweep は proposal なしに進めない。
- `paused` / `killed` を消さない。理由と revisit condition を残す。
- 詳細な時系列は note へ、現在判断は agenda へ置く。
- report の読む順番や artifact index は `notes/reports/README.md` に置く。
- cross-run の CSV、figure、script、log は `analysis/cross_run/<comparison_id>/`
  に置く。
- 毎回、次 action は 0〜3 個に絞る。
- 「何もしない」「待つ」「kill」「report 化する」も有効な decision とする。
- `Feedback To runops` に研究 TODO を混ぜない。
- runops 本体に戻すべき摩擦を見つけたら、作業を止めずに `Feedback To runops`
  に候補として残す。
