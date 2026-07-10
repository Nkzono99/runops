---
name: review-pilot
description: Review completed pilot runs against a research proposal, write a checkpoint decision, and authorize EXPAND only when predefined scientific and operational criteria pass.
---

# Pilot review

この skill は pilot の結果を proposal の事前基準と照合し、full survey に進むかを
決める。結果を見てから判定基準を書き換えない。

## 入力

- `research/proposals/<date>-<topic>.md`
- proposal に列挙した pilot run の `manifest.toml`, status, logs
- required `analysis/summary.json`, artifact index, figures / tables
- related note / report と `research/agenda.md`

## review artifact

`research/reviews/<date>-<topic>.md` を作り、次を残す。

- Experiment ID / proposal path / pilot run_id
- predeclared success, failure, stop, expand criteria
- observed evidence path と欠落 artifact
- numerical / physical validity、confound、runtime / cost variance
- Decision: `EXPAND`, `REVISE`, `STOP`, `WAIT` のいずれか 1 つ
- decision rationale と反証・留保
- authorized next scope（EXPAND の場合も full matrix と cost ceiling を明記）

Decision の意味:

- `EXPAND`: required artifact が揃い、scientific criterion と operational criterion
  を満たした。指定した full matrix だけを投入してよい。
- `REVISE`: 仮説は未判定で、入力・解析・pilot matrix の修正が必要。
- `STOP`: falsification / failure / cost criterion に達した。full submit しない。
- `WAIT`: run 未完了、artifact 不足、人間判断待ち。full submit しない。

## gate

- status だけで `EXPAND` にしない。proposal の metric と artifact を直接確認する。
- failed run を黙って除外して成功率を計算しない。
- proposal にない後付け指標だけで `EXPAND` にしない。
- review に文字列 `Decision: EXPAND` がなく、portfolio の review path と decision が
  一致しない場合、`{{ skill_prefix }}run-all` は full submit へ進まない。
- Decision 後に `research/agenda.md` の Active Experiment Portfolio と Current
  Decision を更新し、`{{ skill_prefix }}note` に checkpoint を追記する。

