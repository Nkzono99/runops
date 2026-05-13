---
name: hops-compact-lab-memory
description: harness-lab が大きくなった時、または人間が依頼した時に、records/dossier から抽象的な mutable knowledge を更新する。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

この skill は `hops lab compact` を置き換えるものではない。`hops lab compact` は deterministic knowledge snapshot、つまり source ID、score、guard、open question へ戻るための索引として扱う。抽象化、統合、反例整理、評価則への昇格はこの skill が行う。

開始時に `.harnessops/project.toml` を読み、PATH に `hops` がなければ `uvx --from harnessops hops <command>` を使う。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えず、records/dossier の作成や分類は CLI に委譲する。

手順:

1. `hops doctor --check-overlay --check-records` を実行する。
2. `hops lab memory lint --warn-only` を実行し、発火理由を確認する。
3. ユーザーが手動実行を依頼した場合、または lint が `needs-abstraction` の場合は `hops lab compact --force` で deterministic snapshot を更新し、続けて `hops lab memory prepare --force` で入力 bundle を作る。
4. `harness-lab/knowledge/lab-memory-input.md` と必要な source record を読む。入力 bundle だけで確信できない主張は、source ID から `records/` または `improvements/` へ戻る。
5. 次の抽象知を更新する。
   - `harness-lab/knowledge/principles.md`: 採用/却下を越えて残った設計原則。各原則に source IDs、適用条件、反例、guard を付ける。
   - `harness-lab/knowledge/patterns.yml`: 再利用可能な改善パターン。failure class、capability、applies_when、avoid_when、evidence、guard、counterexamples を持たせる。
   - `harness-lab/knowledge/anti-patterns.md`: 失敗した改善劇場、過剰一般化、繰り返した摩擦。避ける条件と source IDs を明示する。
   - `harness-lab/knowledge/evaluation-playbook.md`: 評価軸、holdout、判断基準、kill criteria、ベンチマークの経験。
6. 更新後に `harness-lab/knowledge/lab-memory-abstraction.yml` を更新する。少なくとも `schema_version`、`kind: harness_lab_memory_abstraction`、`updated_at`、`source_digest`、`sources`、`outputs` を含め、`source_digest` は `lab-memory-input.yml` の値と一致させる。
7. `hops lab memory lint --warn-only` と `hops doctor --check-overlay --check-records` を再実行する。

抽象化ルール:

- source ID のない原則やパターンを追加しない。
- 採用済み改善だけでなく、却下、反例、regression、open question も保持する。
- 「常に」「必ず」などの強い規則にする前に、適用条件と避ける条件を書く。
- project-specific な研究内容や非公開文脈を `knowledge/` に混ぜない。
- 新しい改善候補が見えた場合、既存 theme なら `hops lab investigate --from <IMP>`、新しい失敗クラスなら `hops lab capture` に分ける。
- 抽象知は採用判断の証拠ではない。判断では必ず source record へ戻る。
