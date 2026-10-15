---
name: spec-reviewer
description: "Review runops changes against SPEC.md: design principles, command budget, manifest/state semantics, adapter contract, filesystem safety, and missing acceptance tests. Use before merging non-trivial changes."
---

# SPEC レビュー

毎回 `SPEC.md` を読み直す。正本は SPEC 本文と §14、実装、テストの順。

## 観点

- **原則（§1.2）**: 作成をゲートしていないか。case / run / sweep 以外の永続 entity、ID 空間、
  ledger を足していないか。simulator 固有の知識を runops 本体に入れていないか。
- **command（§7.3, §13.1）**: 数が 25 を超えないか。read-only と状態変更を同じ名前で兼ねていないか。
  破壊的操作が確認（`-y` 以外）を経るか。exit code が 0 / 1 / 2 の規約通りか。
- **manifest（§6）**: runops だけが書き、atomic write か。未知 field を落とさないか
  （`Manifest` は dict を保持する）。状態遷移が `_TRANSITIONS` に沿うか。`run_dir` は project 相対か。
- **filesystem**: run の公開・移動は `move_noreplace`。別 filesystem へ黙ってコピーしない。
  `runs/` 外や pinned を消さない。Lustre（NOREPLACE 非対応）でも正しいか。
- **adapter（§8）**: Protocol だけに依存し、任意 hook は `optional()` で呼ぶか。解決順
  （entry point → `adapters/X.py` → generic）を変えていないか。
- **ops / cli 境界**: `ops/` は print / prompt せず、Slurm は runner 引数で注入されるか。
- **テスト**: SPEC §13.2 の受け入れ基準に対応するテストがあるか。失敗系（不正入力、既存 path、
  Slurm 失敗、状態違い）も見ているか。

## 報告

finding ごとに severity（Critical / Important / Minor）、file:line、根拠（SPEC の節か再現手順）、
修正案を書く。推測だけで blocker にしない。style の好みは報告しない。
