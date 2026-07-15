# Paper 由来の追加依頼

paper draft から戻る追加解析や図表依頼のために、専用の永続 queue は作りません。
依頼の扱いは通常の Research Workspace と同じです。

- 作業中のメモ、候補、未検証の解析は `.runops/work/<goal-id>/` に置く
- 残すと人が判断した解析だけ `runo research new-result <topic>` で
  `research/results/RNNN-topic/` に昇格する
- 現在の判断や次の一手だけを `research/CURRENT.md` に反映する
- 時系列上残す必要がある経緯は `runo research append` で journal に追記する

paper 側との対応関係は result の `manifest.toml` と `README.md` に source path として
記録します。追加実験や HPC job の投入は、この依頼経路から自動実行しません。
