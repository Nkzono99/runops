---
name: learn
description: Promote a stable, reusable claim from explicit research results into advanced insights or structured facts without copying the whole journal.
---

# 再利用知識へ昇格する

日常の研究記憶は `research/` に置く。この skill は、複数 project から機械的に
再利用する価値が確定した小さな知見だけを `.runops/insights/` または
`.runops/facts.toml` へ昇格する。

1. `runo research status` を確認する。
2. 関連する `research/results/RNNNN-*/README.md` と artifact を読む。
3. journal 全体を複製せず、claim、適用範囲、反例、evidence path を抽出する。
4. narrative insight は `runo knowledge save`、atomic claim は
   `runo knowledge add-fact` を使う。
5. source result ID と artifact path を必ず残す。
6. `research/CURRENT.md` は現在判断が変わった場合だけ更新する。

AI が journal から重要度を推測して一括昇格してはいけない。result への明示昇格が
済んでいない観察は、まず人に候補と理由を示す。
