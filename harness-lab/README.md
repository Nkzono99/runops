# harness-lab

このディレクトリは、このハーネスリポジトリ向けの上流改善実験を保存します。

このディレクトリに置くもの:

- インポート済みのサニタイズ済みフィードバック
- 評価ケース
- メカニズムと中止基準を持つ改善仮説
- 実験と評価スコアカード
- 証拠を伴う採用/却下判断
- メタ改善調査の構造化 research scan
- 一定サイズを超えた lab から圧縮した mutable knowledge layer

GitHub Issues は引き続きタスクトラッカーです。`harness-lab/` は評価と判断の記憶です。

採用済み判断には、証拠、回帰リスク、回帰ガードを明記する必要があります。
`hops lab memory lint` は抽象化の発火基準を確認します。
`hops lab compact` は正本レコードを残したまま deterministic snapshot として `knowledge/lab-memory.yml` と `.md` を更新します。
抽象化が必要な時は `hops lab memory prepare` で入力 bundle を作り、`hops-compact-lab-memory` skill で semantic memory を更新します。
