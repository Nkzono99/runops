# Execution Kernel

Execution Kernel は、Experiment admission、lazy Survey materialization、Run / TestAttempt の生成、job 投入、状態同期、manifest、
provenance を扱う実行状態の層です。
Experiment Layer が「何を走らせるか」を決めるのに対し、Execution Kernel は
「何が生成され、どの状態で、どの由来を持つか」を記録します。

## 目的

- run を一意な実行単位として管理する。
- smoke / debug を T ID の TestAttempt として Run から隔離する。
- 候補 plan は directory を作らず、explicit point selection だけを materialize する。
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
| experiment admission | `experiments/E...toml` | 一つの問い、baseline、budget、有効期限、exit / review |
| smoke/debug receipt | `.runops/test-runs/T.../test-receipt.toml` | Run discovery と scientific evidence から分離 |

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
             |
             +-> completed  (restore)
```

状態操作の原則:

- `runo runs create` と `runo runs sweep --apply --point|--all --expect-plan` だけが `created` Run を作る。
- 引数なしの `runo runs sweep` は read-only plan であり、Run ID を消費しない。
- `runo runs submit` が Slurm に投入し、job id と submit history を記録する。
- `runo runs status` は状態を表示する。live Slurm query を含む場合でも正本は更新しない。
- `runo runs sync` が Slurm 状態を `manifest.toml` / `status/` に反映し、completed
  transition では bounded readiness、reason code、次 command を同じ action result に含める。
- `runo runs cancel` は `scancel` と sync を同時に行う。
- `runo runs archive` / `restore` / `purge-work` / `delete` はライフサイクル操作として扱う。
- 個別 archive / restore は `.runops/lifecycle/` の durable receipt を先に確定し、同じ
  command の再実行で exact preimage / deterministic postimage・namespace・topology を検証して
  中断処理を再開する。不一致時は rollback や receipt cleanup も含めて fail closed とする。
  Run ID と archive の directory / `--all` selection でも、通常 discovery より先に
  receipt の元 source を解決して移動済み Run を recovery plan へ戻す。
- `runo runs review` は terminal outcome の curation を記録し、Result の evidence selection とは分ける。
- `runo runs regenerate --dry-run` は差分確認だけを行い、frozen identity は in-place 更新しない。

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
- Experiment / Survey intent、point / condition / input / execution / provenance / plan hash
- curation review status
- storage tier (`hot|cold`) と form (`full|compacted|metadata_only`)
- submit job id / scheduler metadata

`params_snapshot` は、後から `case.toml` や `survey.toml` が変わっても、
その run が実際にどのパラメータで生成されたかを復元するためのものです。

## Survey と Run の関係

- `survey.toml` は Experiment Layer の設計正本。
- `runo runs sweep <survey_dir>` は直積 / linked axes の候補を lazy に preview する。
- apply 時は current plan hash、Experiment / Survey budget、WIP、review backlog を再検査し、
  選択点だけを Run directory と `manifest.toml` に freeze する。
- 同じ `survey.id + point_id` は existing Run を reuse し、retry で duplicate directory を作らない。
- scientific duplicate の暗黙 reuse は同じ Experiment / Survey owner edge に限定する。
- reuse で新規 Run を公開しなかった場合は Run ID sequence と Experiment usage を増やさない。
- 生成後の各 run は独立した Execution Kernel の単位になる。
- survey 全体の解析は Analysis Layer の `<survey>/summary/` に進む。

## 禁止事項

- `manifest.toml` を手で編集しない。
- `input/`, `submit/job.sh`, `status/` を手で作らない。
- Slurm job id や state を note / research agenda だけに残して正本化しない。
- TestAttempt の T ID / artifact を scientific Result evidence として扱わない。
- TestAttempt の receipt を record/cache reuse する前に保存済み input を再ハッシュする。
- cleanup receipt が固定した directory identity と tree/receipt/input digest が不一致なら、
  tombstone を削除せず pending transaction を保持する。
- `work/` の大容量 output を Git 管理しない。
- completed / archived run を `rm -rf` で消さない。runops lifecycle command を使う。
- sealed Result が include した Run-owned path evidence を `purge-work` で削除しない。

## Human Gate

Human gate が必要な典型例:

- production sweep の一括投入
- Survey の `--all` materialization、または `decision=expand` への変更
- 高コストな rerun / retry
- `runo runs submit --all` (`--yes` は会話上で明示確認済みの場合のみ)
- `runo runs cancel`
- `runo runs delete`
- `runo runs purge-work`
- completed / archived result に影響する操作

## 他レイヤとの関係

- Experiment Layer: campaign / case / survey から run を生成する設計を持つ。
- Analysis Layer: completed run の `analysis/` と survey `summary/` を作る。
- Research Layer: 実行結果から現在判断を更新し、Result-local evidence edge と immutable seal を持つ。
- Harness Layer: submit / delete / purge などの high-cost command に guardrail を置く。
