# Experiment Layer

Experiment Layer は、研究意図を有限な simulation plan に落とし、候補と Run directory を
分離する層です。`campaign.toml`、`experiments/*.toml`、`case.toml`、`survey.toml` の関係で迷った場合は
この文書を正本とします。個々の TOML field は [toml-reference.md](../toml-reference.md)
を参照してください。

## 目的

この層の目的は、自然言語の研究テーマを、一つの bounded question、再利用可能な case、
lazy に探索可能な survey に変換することです。run の生成後の状態、投入、同期、provenance は
[Execution Kernel](execution-kernel.md) が扱います。

```text
campaign.toml
  -> experiments/EYYYYMMDD-NNNN--topic.toml
  -> cases/<simulator>/<case>/case.toml
  -> runs/<survey>/survey.toml (candidate plan)
  -> explicit point selection
  -> Execution Kernel が selected point だけ runs/<survey>/R*/manifest.toml に freeze
```

## 正本

| File / Directory | 役割 | 更新方針 |
|------------------|------|----------|
| `campaign.toml` | 研究目的、仮説、独立変数、観測量 | 研究憲章。大きな変更は human gate |
| `experiments/E...toml` | 一つの問い、baseline、budget、有効期限、exit criteria、review decision | `runo experiments ...` で更新 |
| `cases/<simulator>/<case>/case.toml` | 再利用可能な base configuration | 手で編集可。共通条件はここへ戻す |
| `cases/<simulator>/<case>/summarize.py` | run-level summary / figure hook | Analysis Layer と接続する case-local 解析 |
| `runs/<survey>/survey.toml` | owning Experiment、phase、intent、budget、axis、命名、job override | candidate 設計の正本。手で編集可 |

## 使い分け

- 長期研究の「なぜ」は `campaign.toml`、今判断する一つの問いは Experiment に置く。
- admission 前のアイデアや生成途中 prose は `.runops/work/` に置き、proposal directory を増やさない。
- simulator input の共通条件は `case.toml` と template に置く。
- 掃引軸、点数、semantic naming rule、job override は `survey.toml` に置く。
- agent は parameter alias / semantic group を survey 設計時に一度決め、run ごとの
  命名は `runo runs sweep` の決定的な展開に任せる。
- `runo runs sweep` の既定 plan は read-only。候補数が多くても directory / Run ID は増えない。
- run ごとの実行事実、provenance、state は [Execution Kernel](execution-kernel.md) の
  `manifest.toml` に置く。
- run の結果から作る summary / figure は [Analysis Layer](analysis.md) に置く。
- 現在の高レベルな判断は [Research Layer](research.md) の `research/CURRENT.md` に置く。

## 標準フロー

1. `campaign.toml` の長期目的から、baseline、finite budget、有効期限、exit criterion を持つ Experiment を作る。
2. `runo case new <case>` で case scaffold を作り、input template を整える。
3. `survey.toml` に `experiment_id`, `phase`, `intent.purpose`, budget、axes を定義する。
4. `runo runs sweep <survey_dir>` で candidate count、point ref、plan hash、cost を read-only preview する。
5. pilot point を選び、`--apply --point ... --expect-plan ...` でだけ materialize する。
6. Run を submit / sync / analyze し、terminal outcome を `runo runs review` で確認する。
7. Result evidence を見て Experiment を `expand|revise|stop|accept` と review する。
8. main / followup は `decision=expand` 後に同じ explicit materialization gate を通す。

Experiment の `budget.expires_at` は作成時より未来の UTC offset 付き timestamp とする。
期限到達後も定義と既存 Run は保持するが、新しい standalone / Survey / clone / extend / retry
Run は作らず、`runo triage` から review / close または successor Experiment へ進む。

## Human Gate

Human gate が必要な典型例:

- `campaign.toml` の goal / hypothesis を変える
- 新しい physical model family を導入する
- production sweep を作る
- `--all` materialization または Experiment を `decision=expand` にする
- report / paper 用の主張に直結する experiment design を変える

submit、rerun、delete、purge などの実行ライフサイクル操作の gate は
[Execution Kernel](execution-kernel.md) を参照してください。

## 禁止事項

- `manifest.toml` を手動編集しない。
- `input/`, `submit/job.sh`, `status/` を直接作らない。これらは Execution Kernel の生成物。
- run-local な場当たり修正を正本にしない。再利用価値があれば `case.toml` または
  `survey.toml` に戻す。
- raw output を `materials/` や `research/` にコピーして正本化しない。
- `--dry-run` を外しただけで全候補を作る旧運用を使わない。apply には point selection と plan hash が必要。
- smoke / debug を正式 Run にしない。`runo test smoke|debug` を使う。

## 他レイヤとの関係

- Execution Kernel: survey から run を生成し、submit / sync / manifest / provenance を扱う。
- Analysis Layer: run / survey / cross-run の解析成果物を作る。
- Research Layer: 実験結果から現在判断を更新する。
- Knowledge Layer: 再利用可能な知見だけを `.runops/insights/` / `facts.toml` に昇格する。
- Harness Layer: Agent がこのフローを守るための skill / rule を提供する。
