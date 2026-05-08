# Experiment Layer

Experiment Layer は、研究意図を実行可能な simulation plan と run 記録に落とす層です。
`campaign.toml`、`case.toml`、`survey.toml`、`manifest.toml` の関係で迷った場合は
この文書を正本とします。個々の TOML field は [toml-reference.md](../toml-reference.md)
を参照してください。

## 目的

この層の目的は、自然言語の研究テーマを、再利用可能な case、探索可能な survey、
追跡可能な run に変換することです。

```text
campaign.toml
  -> cases/<simulator>/<case>/case.toml
  -> runs/<survey>/survey.toml
  -> runs/<survey>/R*/manifest.toml
```

## 正本

| File / Directory | 役割 | 更新方針 |
|------------------|------|----------|
| `campaign.toml` | 研究目的、仮説、独立変数、観測量 | 研究憲章。大きな変更は human gate |
| `cases/<simulator>/<case>/case.toml` | 再利用可能な base configuration | 手で編集可。共通条件はここへ戻す |
| `cases/<simulator>/<case>/summarize.py` | run-level summary / figure hook | Analysis Layer と接続する case-local 解析 |
| `runs/<survey>/survey.toml` | sweep axis、命名、job override | survey 設計の正本。手で編集可 |
| `runs/<survey>/R*/manifest.toml` | run の state、origin、provenance、job 履歴 | runops 管理。手動編集しない |
| `runs/<survey>/R*/input/` | freeze 済み simulator input | runops 生成物。直接作らない |
| `runs/<survey>/R*/submit/` | `job.sh` などの投入 script | runops 生成物。直接作らない |
| `runs/<survey>/R*/work/` | simulator runtime output | Git 管理しない raw output |
| `runs/<survey>/R*/status/` | Slurm / sync 状態補助 | runops 管理 |

## 使い分け

- 研究の「なぜ」は `campaign.toml` に置く。
- simulator input の共通条件は `case.toml` と template に置く。
- 掃引軸、点数、命名、job override は `survey.toml` に置く。
- run ごとの実行事実、provenance、state は `manifest.toml` に置く。
- run の結果から作る summary / figure は [Analysis Layer](analysis.md) に置く。
- 現在の高レベルな判断は [Research Layer](research.md) の `research/agenda.md` に置く。

## 標準フロー

1. `campaign.toml` に研究目的、仮説、変数、観測量を定義する。
2. `runo case new <case>` で case scaffold を作る。
3. `case.toml` と input template を研究目的に合わせて編集する。
4. `survey.toml` で sweep axis と job override を定義する。
5. `runo runs sweep <survey_dir> --dry-run` で展開数と資源量を確認する。
6. `runo runs sweep <survey_dir>` で run を生成する。
7. `runo runs submit` / `runo runs submit --all` で投入する。
8. `runo runs status` / `runo runs sync` で状態を追跡する。
9. 完了後は `runo analyze summarize` / `collect` で Analysis Layer に進む。

## Human Gate

Human gate が必要な典型例:

- `campaign.toml` の goal / hypothesis を変える
- 新しい physical model family を導入する
- production sweep を作る
- 高コストな rerun / bulk submit を行う
- `runs delete`, archive purge, 重要な結果の削除を行う
- report / paper 用の主張に直結する experiment design を変える

## 禁止事項

- `manifest.toml` を手動編集しない。
- `input/`, `submit/job.sh`, `status/` を直接作らない。
- run-local な場当たり修正を正本にしない。再利用価値があれば `case.toml` または
  `survey.toml` に戻す。
- raw output を `notes/`, `materials/`, `research/` にコピーして正本化しない。

## 他レイヤとの関係

- Analysis Layer: run / survey / cross-run の解析成果物を作る。
- Research Layer: 実験結果から現在判断を更新する。
- Knowledge Layer: 再利用可能な知見だけを `.runops/insights/` / `facts.toml` に昇格する。
- Harness Layer: Agent がこのフローを守るための skill / rule を提供する。
