# Execution Kernel

Execution Kernel は、survey / run の生成、job 投入、状態同期、manifest、
provenance を扱う実行状態の層です。
Experiment Layer が「何を走らせるか」を決めるのに対し、Execution Kernel は
「何が生成され、どの状態で、どの由来を持つか」を記録します。

## 目的

- run を一意な実行単位として管理する。
- Slurm job の投入・同期・キャンセルを run state に反映する。
- `manifest.toml` を run の正本として保つ。
- 入力、job script、runtime output、status、provenance を同じ run directory に束ねる。
- Agent / 人間が同じ run state から再開できるようにする。

## 正本

| 対象 | 場所 | 更新方針 |
|------|------|----------|
| run state / provenance | `runs/<path>/R*/manifest.toml` | runops 管理。手動編集しない |
| state history 補助 | `runs/<path>/R*/status/` | runops 管理 |
| frozen input | `runs/<path>/R*/input/` | runops 生成。直接作らない |
| submit script | `runs/<path>/R*/submit/` | runops 生成。直接作らない |
| runtime output | `runs/<path>/R*/work/` | simulator / Slurm 出力。Git 管理しない |
| run analysis | `runs/<path>/R*/analysis/` | Analysis Layer の run-local 成果物 |
| survey definition | `runs/<survey>/survey.toml` | Experiment Layer の survey 設計 |

## 標準 run directory

```text
runs/<survey>/R20260508-0001/
  manifest.toml
  input/
  submit/
    job.sh
  work/
  status/
  analysis/
```

`manifest.toml` はこの directory の正本です。
run_id は不変ですが、run directory path は整理や分類のために変わる可能性があります。

## 状態遷移

標準状態:

```text
created -> submitted -> running -> completed
created/submitted/running -> failed
submitted/running -> cancelled
completed -> archived -> purged
```

状態操作の原則:

- `runo runs create` / `runo runs sweep` が `created` run を作る。
- `runo runs submit` が Slurm に投入し、job id と submit history を記録する。
- `runo runs status` は状態を表示する。live Slurm query を含む場合でも正本は更新しない。
- `runo runs sync` が Slurm 状態を `manifest.toml` / `status/` に反映し、completed
  transition では bounded readiness、reason code、次 command を同じ action result に含める。
- `runo runs cancel` は `scancel` と sync を同時に行う。
- `runo runs archive` / `purge-work` / `delete` はライフサイクル操作として扱う。

## Provenance

Execution Kernel は run 生成時・投入時・同期時に、再現性に必要な由来を
`manifest.toml` に残します。

主な provenance:

- run id / display name / created_at
- origin case / survey / parent run
- classification / variation
- simulator name / adapter / resolver mode
- executable path / hash / source repo / git commit
- launcher / site / job resources
- params snapshot
- submit job id / scheduler metadata

`params_snapshot` は、後から `case.toml` や `survey.toml` が変わっても、
その run が実際にどのパラメータで生成されたかを復元するためのものです。

## Survey と Run の関係

- `survey.toml` は Experiment Layer の設計正本。
- `runo runs sweep <survey_dir>` は survey の直積 / linked axes を展開し、
  各点を run directory と `manifest.toml` に freeze する。
- 生成後の各 run は独立した Execution Kernel の単位になる。
- survey 全体の解析は Analysis Layer の `<survey>/summary/` に進む。

## 禁止事項

- `manifest.toml` を手で編集しない。
- `input/`, `submit/job.sh`, `status/` を手で作らない。
- Slurm job id や state を note / research agenda だけに残して正本化しない。
- `work/` の大容量 output を Git 管理しない。
- completed / archived run を `rm -rf` で消さない。runops lifecycle command を使う。

## Human Gate

Human gate が必要な典型例:

- production sweep の一括投入
- 高コストな rerun / retry
- `runo runs submit --all` (`--yes` は会話上で明示確認済みの場合のみ)
- `runo runs cancel`
- `runo runs delete`
- `runo runs purge-work`
- completed / archived result に影響する操作

## 他レイヤとの関係

- Experiment Layer: campaign / case / survey から run を生成する設計を持つ。
- Analysis Layer: completed run の `analysis/` と survey `summary/` を作る。
- Research Layer: 実行結果を見て現在判断を更新する。
- Harness Layer: submit / delete / purge などの high-cost command に guardrail を置く。
