# runops 使い方ガイド

runops で計算を進める流れを、場面ごとに説明します。人が打つコマンドは `runo init` だけで、
ほかはエージェント（Codex や Claude Code）に頼みます。各節では頼み方の例と、その裏で
エージェントが実行する `runo` コマンドを並べます。コマンドと設定の一覧は
[リファレンス](reference.md) にあります。

## 1. 始める

```bash
uv tool install runops
mkdir lunar-sheath && cd lunar-sheath
runo init
```

`runo init` は計算機の種類（site）と使う simulator を尋ねます。site はホスト名から推定するので、
京大スパコンのログインノードなら Enter で進めます。終わると次のものができています。

| できるもの | 役割 |
|---|---|
| `runops.toml` | site、simulator、launcher、整理のしきい値などの設定 |
| `cases/`、`runs/` | 入力テンプレートと、実行した run の置き場所 |
| `LOG.md`、`notes/` | 判断の記録と、再利用する知見の置き場所（[6 節](#6-記録を残す)） |
| `.venv/` | simulator の Python package（adapter と skill を含む） |
| `AGENTS.md`、`CLAUDE.md`、`.agents/skills/`、`.claude/skills/` | エージェント向けの規則と skill |

この directory で Codex か Claude Code を起動し、調べたいことを話しかけてください。
エージェントは `AGENTS.md` と skill を読んで `runo` を使います。最初の依頼の例です。

> MPIEMSES3D で平板シースを計算したい。cookbook の例を元に case を作って。
> gr20001a に 800 並列、120 時間で。

## 2. case と run の分け方

runops が扱う名詞は case、run、sweep の 3 つです。

| 名詞 | 中身 | 置き場所 |
|---|---|---|
| case | 再利用する入力テンプレート。`case.toml` と base 入力ファイル | `cases/<name>/` |
| run | 1 回の実行。入力を凍結し、状態を `manifest.toml` に持つ | `runs/<case>/<run_id>--<label>/` |
| sweep | 1 つの case から値を振って run をまとめて作る操作 | `runs/<case>/<sweep_label>/` |

**値を変えるだけなら case を増やさず、run で表します。** case を増やすのは、base 入力ファイルの
構造（境界の種類、粒子種の数など）が変わるときだけです。値ごとに case を作ると、
`flat_size_1x`、`flat_uv_off`、`flat_retry` のような case が増え、どれが何だったか追えなくなります。

| やりたいこと | 頼み方の例 | 裏のコマンド |
|---|---|---|
| 1 つの値を変えて試す | flat で wc を 0.147 にして 1 本作って | `runo new flat --set plasma.wc=0.147 --why "..."` |
| 前の run から少し変える | R20261015-0002 の nx だけ倍にして | `runo new --from R20261015-0002 --set tmgrid.nx=8000 --why "..."` |
| 値を振る | wc を 0, 0.147, 0.294 で振って | `runo sweep flat --set plasma.wc=0,0.147,0.294 --why "..."` |
| 構造が違う入力を作る | flat を元に、穴の空いた境界の case を作って | `runo case new hole --from flat` |

`--set` の key は base 入力の dotted key です（`plasma.wc`、配列なら `species.0.wp`）。
値は TOML のリテラルとして読まれます（`3`、`1.5e-6`、`true`、`[1, 2]`）。

どの run にも `--why`（その run で確かめたいこと）が付きます。エージェントには、依頼の中で
目的も伝えてください。後で `runo list` を見たとき、run を区別する手がかりになります。

作った run の `manifest.toml` と `input/` は変更しません。入力を直したいときは新しい run を作ります。
同じ入力の run が既にあると、作成時に警告が出ます。

## 3. 試してから本計算

いきなり本計算を投げず、短い scratch run で動作を確かめてから投入する流れです。

> 100 step だけ smoke で試して。通ったら wc を 3 通りに振った候補を見せて。

エージェントは次の順に進めます。

1. `runo new flat --scratch --set ... --why "smoke"` で scratch run を作って投入する。
   scratch run は `runs/_scratch/` に置かれ、既定の `runo list` には出ません。
   `scratch_ttl_days`（既定 7 日）を過ぎると `runo tidy` の削除候補になります。
2. `runo sync` と `runo log RUN --err` で、起動直後に落ちていないか確かめる。
3. `runo sweep flat --set plasma.wc=0,0.147,0.294 --why "..."` で候補を表示する。
   この段階では何も作られません。表には候補ごとの値、label、合計の core-hours が出ます。
4. あなたが確認したら、`runo sweep ... --apply --submit` で run を作って投入する。

依頼の言葉が、エージェントに許す操作の範囲を決めます。

| 依頼の言葉 | エージェントがしてよいこと |
|---|---|
| 「作って」 | run の作成まで。投入はしない |
| 「流して」「投げて」 | 作成と投入 |
| 「試して」 | 短い scratch run の作成と投入。本計算は投げない |

投入、削除、整理、移行の前には、エージェントが対象の run、partition、資源量、core-hours を示して
確認を取ります。`runo` 自体も、複数 run の投入や削除の前に確認を求めます。

資源量（partition、walltime、並列数）は case の `[job]` に書きます。1 回だけ partition を
変えるなら「今回は gr20001b で投げて」と頼めば `runo submit RUN --partition gr20001b` になります。

## 4. 様子を見る

> 先週投げた run の状況を見て。失敗していたら原因をノートに残して。

| コマンド | 内容 |
|---|---|
| `runo sync` | 投入済み・実行中の run の状態を Slurm から更新する |
| `runo list` | 実行中、作成済み、直近 30 日、pin した run を表示する |
| `runo status RUN` | 1 つの run の状態（Slurm には問い合わせない） |
| `runo log RUN --err` | 最新 job の stderr の末尾 |
| `runo summarize RUN` | adapter による結果の要約を `analysis/summary.json` に書く |

`runo sync` は、active な run が何件あっても `squeue` と `sacct` を 1 回ずつしか呼びません。
エージェントには `squeue` を直接叩かせず、`runo sync` を使わせてください。

### 状態の決まり方

run の状態は `created → submitted → running → completed | failed | cancelled` と進みます。
`sync` は次の順で終わった run の状態を決めます。

1. Slurm が状態を返す job はその状態に従う。Slurm が `COMPLETED` でも、adapter が出力を見て
   失敗と判断すれば `failed` にする。
2. Slurm の記録から消えた job は、job.sh が終了時に書く `submit/exit.<job_id>` を見る。
   exit code が 0 なら adapter の判定、0 以外なら `failed`。`module load` や `pre_commands` などの
   準備が失敗した job は program を起動せずに終わり、`failed` になる。
3. その記録も無ければ adapter の判定に従い、判定できなければ `failed`。

runops が知らない Slurm 状態の job は状態を変えず、`last_slurm_state` に状態名だけを残します。

### 長い job の見守り

本計算の投入は、Slurm が受け付けた時点で完了です。エージェントは job id を報告して止まります。
見守ってほしいときは、そう頼んでください。

> 投げたら、最初にちゃんと動き出したかだけ見て。

エージェントは起動直後に 1 回確認し、その後は予定の終了時刻のあたりで確認します。
`tail -f` や短い間隔での状態確認の繰り返しはしません。期限が来ても、エージェントが自分の判断で
キャンセルや再投入をすることはありません。

### 失敗したとき

| 状況 | 頼み方の例 | 裏のコマンド |
|---|---|---|
| 原因を調べる | R20261016-0003 が落ちた理由を調べて | `runo log RUN --err`、`runo summarize RUN`、`runo note RUN "..."` |
| 一時的な障害で、同じ入力で流し直す | 同じ入力でもう一度投げて | `runo retry RUN`、`runo submit RUN` |
| 入力を直して流し直す | dt を半分にして作り直して | `runo new --from RUN --set ... --why "..."` |
| 止める | R20261016-0004 を止めて | `runo cancel RUN` |

`retry` は `failed` / `cancelled` の run を `created` に戻し、試行回数を 1 つ増やします。
`work/` は消しません。

## 5. 続きを流す

> R20261015-0003 の続きを 2 倍の step で。

`runo new --from RUN --continue` で、終わった run の出力から再開する run を作ります。
再開の方法は simulator ごとに違い、adapter が対応している場合だけ使えます
（現在は MPIEMSES3D が対応し、`SNAPSHOT1` から再開します）。新しい run は元の run を `parent_run` として記録します。

前の job が終わるのを待って投入したいときは、「R20261016-0005 が成功したら投げて」と頼めば
`runo submit RUN --afterok <job_id>` になります。

## 6. 記録を残す

記録の置き場所は 3 つに決まっています。

| 何を | どこに | 頼み方の例 |
|---|---|---|
| 1 つの run についての観察 | `runo note RUN "..."`（manifest に日時付きで残る）か run の `notes.md` | この run は 3 万 step で電位が飽和した、とメモして |
| 複数の run をまたぐ結論と次の判断 | `LOG.md` に日付見出しで追記 | 今日の scan の結論を LOG にまとめて |
| 再利用する式、手法、落とし穴 | `notes/<topic>.md`（1 topic 1 file） | Debye 長の見積もり方を notes に残して |

エージェントはこれ以外の場所（`research/`、`analysis/*.md`、`runs/` の下など）にノートを作りません。
`notes/` に似た topic の file があれば、新しく作らずに追記します。

`runo context` は `LOG.md` の末尾と `notes/` の file 名を表示します。エージェントは作業の始めに
これを読むので、前回の続きから話を始められます。

## 7. 整理する

run は消さなくても `runo list` が古いものを隠しますが、directory とディスクは増えていきます。

> 古い run を整理して。消すものと archive するものを先に見せて。

`runo tidy` は候補を表示するだけで、何も変更しません。

| 種類 | 条件 | 処理 |
|---|---|---|
| `expired-scratch` | 期限切れの scratch run | 削除 |
| `stale-failed` | 30 日より古い failed / cancelled で、`why` もノートも無い | 削除 |
| `old-completed` | 90 日より古い completed | archive |
| `orphan-job` | 投入済みなのに Slurm が知らない | `sync` で状態を確定 |
| `unused-build` | どの run も使っていない build cache | 削除 |

候補を確認したら `runo tidy --apply` で実行します。archive は `runs/_archive/` への移動で、
run id で引き続き見つかり、`runo restore` で戻せます。

論文の図に使う run や基準にする run は pin しておくと、`list` に常に表示され、`tidy` や `delete`
の対象になりません。

> R20261015-0002 は図 3 の基準なので残しておいて。

終わった run の出力が大きいときは、「R20261015-0002 の work を片付けて」と頼めば
`runo tidy --purge-work RUN` で `work/` の中身を消します。adapter が指定するファイル
（要約やログなど）は残ります。adapter を読み込めないときは、何も消さずにエラーになります。

日数のしきい値は `runops.toml` の `[defaults]` にあります。「この project では failed は
14 日で消していい」と頼めば、エージェントが書き換えます。

## 8. simulator を足す、更新する

| やりたいこと | 頼み方の例 | 裏のコマンド |
|---|---|---|
| 状態を点検する | runops の環境を点検して | `runo doctor` |
| package の simulator を足す | BEACH も使えるようにして | `runops.toml` に追記、`runo update -y` |
| 手元で改造した版を足す | ~/BEACH-dev をビルドして、別の simulator として登録して | `resolver_mode = "local_source"`、`runo build NAME` |
| 自作プログラムを使う | ./run.sh を simulator として登録して | `adapter = "generic"`、`command = "./run.sh"` |
| 更新する | runops と simulator を最新にして | `uv tool upgrade runops`、`runo update -y` |

`runo update` は simulator package を更新し、package に同梱された skill を配置し直します。
`AGENTS.md` は `<!-- runops:begin -->` から `<!-- runops:end -->` までだけを書き換えるので、
その外に書いた project 固有の規則は残ります。

`local_source` の simulator は、source の commit ごとに `.runops/build/<sim>-<commit>/` へ
build し、run の manifest に commit と executable の hash を記録します。後から「この run は
どの版で計算したか」を確かめられます。

simulator 用の adapter を自分で書く方法は [adapter ガイド](adapter.md) にあります。

## 9. v1 の project から移る

> この project を runops v2 に移行して。

エージェントは先に `runo migrate-v1 --dry-run` で変換計画を見せます。確認すると変換を実行します。

- v1 の設定と harness は `.runops/v1-backup/<日時>/` に退避され、削除はされません。
- 各 run の v1 manifest は `manifest.v1.toml` として同じ directory に残ります。
- `research/`、`materials/`、`refs/` は動かしません。場所は `notes/README.md` に追記されます。
- run directory は移動しません。v1 の配置のまま `runo list --all` に表示されます。

実運用中の project を移行するときは、先にコピーで試すよう頼むと安全です。

## 10. よくあるつまずき

- **KUDPC のログインノード**: `runo` の操作自体はログインノードで実行できます。simulator の
  build や重い解析は計算ノードで行います。エージェントには KUDPC 用の plugin の規則に従わせてください。
- **`runo` が project を見つけない**: `runo` は現在の directory から上に向かって `runops.toml` を
  探します。project の外で実行すると exit code 2 で止まります。
- **run directory を動かした**: `runs/` の下なら自由に移動して構いません。run id で見つかります。
  `runs/` の外に出した run は扱えません。
- **確認を求められて止まる**: 端末以外から `runo` を実行すると確認の入力ができないため、
  `-y` が無い破壊的な操作はエラーになります。エージェントはあなたの確認を取ってから `-y` を付けます。
- **skill が古い**: runops や simulator を更新した後は `runo doctor` が skill の更新を提案します。
  「skill を更新して」と頼めば `runo update --skills-only` を実行します。
