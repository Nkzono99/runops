# runops v2 SPEC

Status: implemented (2.0.0.dev0)。§14 に実装時の決定をまとめる
Target version: `runops 2.0.0`
Audience: runops v2 を保守・拡張する agent / 開発者

---

## 0. この文書の読み方

- 本文書は v2 の **唯一の仕様** である。v1 の `SPEC.md`、`docs/`、`.codex/rules/` は
  v2 実装の参照にしてよいが、v2 の要件ではない。v1 にあって本文書にないものは
  **意図的に削除された機能** であり、復活させない。
- "MUST" / "MUST NOT" / "SHOULD" / "MAY" は RFC 2119 の意味で使う。
- 判断に迷ったら §1.2 の設計原則に戻る。原則同士が衝突したら番号の小さい方を優先する。

---

## 1. 目的と原則

### 1.1 v2 が解く問題

v1 は run directory と note の増殖に対し、作成前の admission（Experiment、budget、
expires-at、plan hash gate、TestAttempt 分離、Result seal、receipt 付き archive）を
積み上げて対処した。結果として

- 日常の run 作成に前置き儀式が必要になり、使われなくなった
- 管理対象の名詞が増え（experiments / test-runs / results / journal / knowledge /
  facts / receipts）、増殖物の種類がむしろ増えた
- コードが約 64k 行、CLI が約 100 command になり、保守できなくなった
- simulator 固有の知識を Codex plugin に分離したが、plugin の install / activation を
  ユーザーが手動で行う必要があり、準備コストで使われなくなった

v2 は **「run 台帳 + job 投入 + simulator 連携の取り込み」** だけに責務を戻し、
増殖は **置き場所の規約・既定で隠す一覧・整理コマンド** で吸収する。

### 1.2 設計原則（優先順）

1. **run directory が主単位。manifest.toml が正本。** すべての操作は run id か
   run directory を基点にする。run id は不変、path は可変。
2. **作成をゲートしない。** 条件を満たさないと run を作れない、という仕組みを
   作らない。代わりに作成理由を記録し、一覧で見せ、整理を提案する。
3. **名詞は case / run / sweep の 3 つ。** 新しい永続 entity（別 namespace、別 ID 空間、
   別 ledger）を追加しない。
4. **中身ではなく機構を同梱する。** simulator 固有の adapter と agent 向け知識は
   simulator 側の Python package が持ち、runops はそれを project に展開する機構だけを持つ。
5. **MPI に介入しない。** runops は job.sh を生成して sbatch するだけ。rank ごとの
   wrapper にならない。
6. **1 command は 1 つの明確な効果。** read-only な command と state を変える command を
   同じ名前で兼ねない（例外: `--apply` flag のある `sweep` / `tidy`）。
7. **小さく保つ。** 目標規模は §13 を参照。規模目標を超える機能は本文書の改訂なしに追加しない。

### 1.3 実運用から読み取った要件

v1 で運用した 2 つの project（`project_dust_release`: BEACH、run 120、case 44、
`ion_depression`: EMSES、run 50、case 3）を調べて分かった事実と、v2 への反映。

| 観察 | v2 での扱い |
|---|---|
| run は `runs/<case名>/` で topic ごとに置かれていた。日付では置いていない | 既定の配置先を `runs/<case>/` にする（§3） |
| BEACH project では case が 44 個に増え、名前が `_size_1x` / `_uv_off` / `_retry` / `_smoke` のように variation を encode していた。`[params]` は空で、差分は base 入力ファイル側にあった | 増殖の主因は「run ではなく case で variation を表現した」こと。v2 は `new --set` と `new --from RUN` を variation の正規経路にし、adapter は dotted key で TOML 入力を上書きできることを要件にする（§5、§8.1） |
| 同じ adapter で patched build を 6 つ `simulators.toml` に並べ、`.runops/work/<name>-<hash>/bin/` に置いていた | `local_source` の build cache を `.runops/build/<sim>-<commit>/` として正式化する（§4.1） |
| BEACH は OpenMP。`[job]` に `processes` / `threads` / `cores` / `pre_commands` を使う | `[job]` はこれらを維持する（§5） |
| manifest は `[[job.attempts]]` で投入履歴を持ち、`run_dir` は絶対 path だった | attempts は維持。`run_dir` は project 相対にし、移行で変換する（§6.2、§11） |
| run 内の note はほぼ無く（3 件）、知見は `research/`（md 40k 行、うち legacy archive 1,688 file）と `.runops/insights/`（20 件）にあった | note の置き場所を run / `notes/` / `LOG.md` の 3 つに固定し、runops はそれらを管理しない（§9） |
| `materials/`（論文、tex、pdf）と `refs/` にユーザー資料があった | runops は触らない。移行でも触らない（§11） |
| v1 harness は `runs/` 直下にも `AGENTS.md` / `CLAUDE.md` を生成していた | v2 は project root 以外に harness file を置かない（§10） |
| `survey.toml` が `runs/` 配下に 18 個あった | v2 の sweep は永続 file を作らない。移行では `origin.sweep` の補完にだけ使う（§11） |

### 1.4 非目標（v2 では実装しない）

以下は v1 にあったが v2 では **実装しない**。将来必要になれば本文書を改訂してから足す。

- Experiment / campaign / admission / budget / expires-at / exit criteria
- survey plan hash と `--expect-plan` gate
- TestAttempt（T ID、test-receipt、cache reuse）
- Result / seal / evidence edge / publication export / story audit
- research journal / CURRENT.md / rotation / bounded budget
- knowledge / facts / knowledge source / profile
- receipt 付き bundle archive / tombstone / forward recovery
- project-state migration framework（v1→v2 の一回限りの変換 command は §11 で定義する）
- harness の versioned chain 更新（`update-harness --apply-chain`）
- MCP server（CLI の `--json` 出力で代替する。agent は CLI を直接呼ぶ）
- project 横断の knowledge source（`[knowledge]`、`refs/knowledge`、`hpc-shared-knowledge` の mount）。
  v1 運用でも使われなかった。別 project を参照したいときは `AGENTS.md` にその path を書くだけでよい
- 他の runops project への link 機能。同上
- demo replay
- Codex plugin 推薦 metadata（`codex_plugins`、`install_hint`、`activation_hint`）

---

## 2. 用語

| 用語 | 意味 |
|---|---|
| project | `runops.toml` を root に持つ directory。git 管理を想定 |
| case | 再利用可能な入力テンプレート。`cases/<name>/case.toml` と base 入力ファイル |
| run | 1 回の実行。`manifest.toml` を持つ directory。id は `R<YYYYMMDD>-<NNNN>` |
| sweep | 1 つの case から parameter を振って複数 run を一括生成する操作。永続 entity ではなく、生成された run の `origin.sweep` label と親 directory で表現する |
| scratch run | smoke / debug 用の短命 run。通常 run と同じ manifest を持ち、`run.scratch = true` と期限を持つ |
| adapter | simulator 固有処理（入力生成、コマンド構築、完了判定、要約）を実装する Python class。`runops.adapters` entry point で発見する |
| launcher | MPI 起動方式（srun / mpirun / mpiexec）。job.sh の実行行を生成する |
| agent context | simulator package が同梱する agent 向け skill / reference。runops が project 内にコピーする |

---

## 3. project layout

```text
<project>/
  runops.toml              # project 設定の正本（§4）
  cases/
    <case_name>/
      case.toml            # §5
      <base input files>   # adapter が指定する base template（例: plasma.toml）
      input/               # 追加ファイル。run の input/ にそのままコピー
  runs/
    <case_name>/
      <run_id>--<label>/           # 単発 run
      <sweep_label>/
        <run_id>--<label>/         # sweep で生成された run
    _scratch/
      <run_id>--<label>/           # scratch run
    _archive/
      <case_name>/...              # archive された run（元の相対 path を保つ）
  adapters/                # 任意。project ローカル adapter `<name>.py`（§8.1）
  notes/                   # 永続的な知見。1 topic 1 file。runops は管理しない（§9）
  LOG.md                   # project 全体の追記専用ログ（§9）
  AGENTS.md                # agent 向け入口（§10）
  CLAUDE.md                # `@AGENTS.md` のみ
  .agents/skills/          # runops が展開する skill（§10）
  .claude/skills/          # 同上。両方に同じ内容を置く
  .runops/
    skills.lock            # 展開した skill の由来と version（§8.2）
    index.toml             # run id -> path cache（§7.2）
    id.lock                # run id 採番用 lock
    run.lock               # manifest の読み直し・更新用 lock（submit / cancel / retry / sync）
    last_run_id            # 最後に払い出した run id。削除後も同じ id を再利用しないため
    v1-backup/<stamp>/     # migrate-v1 が退避した v1 の設定と harness（§11）
    build/
      <sim>-<commit>/      # local_source の build cache（§4.1）
    .gitignore
  .venv/                   # simulator package の install 先（git 管理外）
```

- `runs/` 配下の path は **規約であり制約ではない**。ユーザーは run directory を
  `runs/` 配下の任意の場所に移動してよい。runops は manifest の `run.id` で run を
  見つける（§7.2）。
- 既定の配置先は `runs/<case_name>/`。`--dest` で上書きできる。`_` で始まる
  directory（`_scratch`、`_archive`）は runops が予約する。
- run directory の中（自身と子孫）には run を置けない。`--dest` が既存 run の中なら拒否し、
  `delete` は中に別の run があれば拒否する（§7.2 の走査は manifest のある directory で止まる）。
- run id は `R<YYYYMMDD>-<NNNN>`。その日の既存 run と `.runops/last_run_id` の大きい方に 1 を足す。
  run を削除しても番号は再利用しない（ログやノートに残った id が別の run を指さないように）。
  `last_run_id` を失っても既存 run からの採番に戻るだけで、動作は壊れない。
- run は同じ親 directory の `.<name>.staging` で組み立ててから rename で公開する。
  rename は `renameat2(RENAME_NOREPLACE)` を使い、filesystem が対応しない場合
  （KUDPC の Lustre は EINVAL を返す）は project lock 下で存在確認してから `rename` する。
  archive / restore も同じ関数を使い、別 filesystem への移動はコピーせずエラーにする。
- `materials/`、`refs/`、`scripts/` などユーザーが置く directory は runops の関知外。
  runops は `runs/`、`cases/`、`.runops/`、`.agents/skills/`、`.claude/skills/`、
  `AGENTS.md`、`CLAUDE.md`、`runops.toml` 以外を作成・変更しない（`LOG.md`、`notes/`
  は `init` の雛形生成のみ）。

---

## 4. runops.toml

v1 の `simulators.toml`、`launchers.toml`、`site.toml` を 1 ファイルに統合する。
v1 の field 意味は変えない。

```toml
schema = 2

[project]
name = "lunar-sheath"

[site]
name = "kudpc"
resource_style = "rsc"            # "standard" | "rsc"
modules = ["intel/2023.2", "intelmpi/2023.2"]
stdout = "stdout.%J.log"
stderr = "stderr.%J.log"
extra_sbatch = []
setup_commands = []

[site.env]
OMP_PROC_BIND = "spread"

[simulators.emses]
adapter = "emses"                 # runops.adapters entry point 名
package = "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git"
executable = "mpiemses3D"
resolver_mode = "package"         # "package" | "local_executable" | "local_source"
modules = ["hdf5/1.12.2_intel-2023.2-impi", "fftw/3.3.10_intel-2022.3-impi"]
# resolver_mode = "local_source" の場合のみ
# source_repo = ""
# build_command = "make -j"

[launchers.srun]
kind = "srun"                     # "srun" | "mpirun" | "mpiexec" | "none"（MPI launcher なし）
use_slurm_ntasks = true
args = ""
modules = []

[defaults]
launcher = "srun"
scratch_ttl_days = 7              # scratch run の期限（日）
list_since_days = 30              # runo list が既定で表示する期間（日）
tidy_failed_days = 30             # why もノートも無い failed / cancelled を削除候補にするまで（日）
tidy_archive_days = 90            # completed を archive 候補にするまで（日）
label_max_length = 48             # run 名の自動ラベルの最大文字数（8 以上）
```

規則:

- `simulators.<name>.package` は省略可。省略時は adapter の `pip_packages()` を使う。
  指定時はそちらが優先（ユーザーが fork や pin を使えるようにする）。
- 同じ `adapter` を持つ `[simulators.*]` を複数定義してよい（patched build や
  branch 違いを並べる用途）。case の `simulator` はこの name を指す。
- `[site]`、`[launchers.*]`、`[simulators.*].modules` の merge 順は v1 と同じ:
  site modules → launcher modules → simulator modules。
- 未知の key は **warning を出して無視** する（fail しない）。
- `[defaults]` の日数と文字数は正の数でなければ設定エラー（exit code 2）。project ごとの運用方針
  （整理の目安、表示期間、命名の長さ）はここに置き、コードに埋め込まない。

### 4.1 resolver_mode と build cache

| mode | executable の解決 |
|---|---|
| `package` | `.venv/bin/<executable>`。無ければ `doctor` が `runo update` を案内 |
| `local_executable` | `executable` を絶対 path または PATH で解決 |
| `local_source` | `source_repo` の HEAD commit を取り、`.runops/build/<name>-<short_commit>/` が無ければ `build_command` をそこで実行する。`executable` は build dir 相対 |

- `local_source` の build は `runo new` / `runo submit` 時に executable が無ければ自動で行う。
  `runo build SIM [--force]` で明示的にも行える（command 数に含める）。
- build dir 名は `<sim>-<short_commit>[-dirty]-<digest>`。digest は `build_command` と、dirty なら
  build にコピーする全ファイル（追跡済みと未追跡、ignore 以外）の内容の hash。未追跡ファイルの
  内容や `build_command` を変えると別の build になる。コピー後に source が変わっていたら build を中止する。
  dirty なら manifest に `git_dirty = true` を記録する。
- build cache は `tidy` が `unused-build` として挙げる（どの非 archived run の manifest からも
  参照されない build dir）。

---

## 5. case.toml

```toml
[case]
name = "flat_surface"
simulator = "emses"
launcher = "srun"                 # 省略時 defaults.launcher
description = "Flat surface sheath"
tags = ["sheath", "2d"]

[job]
partition = "gr20001a"
walltime = "120:00:00"
# MPI 型 (EMSES など)
nodes = 1
ntasks = 800
# OpenMP / hybrid 型 (BEACH など)。rsc style では --rsc p=..:t=..:c=.. になる
# processes = 1
# threads = 112
# cores = 112
# qos, extra_sbatch, pre_commands も可。意味は v1 と同じ

[params]
"tmgrid.nx" = 4000
"plasma.wc" = 0.0

[naming.aliases]            # 任意。label 生成時の key 短縮
"plasma.phiz" = "angle"
```

- `[classification]` は廃止し `case.tags` に統合する。
- `[job]` の field は v1 と同じ集合を受け付ける: `partition`、`qos`、`walltime`、
  `nodes`、`ntasks`、`processes`、`threads`、`cores`、`extra_sbatch`、`pre_commands`。
  `resource_style = "rsc"` のとき `processes/threads/cores` を `--rsc` に、
  `standard` のとき `nodes/ntasks` を `#SBATCH` に写す。
- `cases/<name>/` 直下の base 入力ファイル（adapter の `case_template()` が返す
  ファイル）と `input/` 配下は、run 作成時に run の `input/` にコピーされ、その後
  adapter の `render_inputs()` が `[params]` を適用して上書きする。
- `runo new` / `runo sweep` の `--set k=v` は `[params]` の上書きである。
  既存 key でなくても受け付ける（adapter の `validate_params()` が warning を出せる）。
  warning には判定した adapter と package version を付け、executable が package 由来でない
  （`local_source` / `local_executable`）ときは「schema が古いだけかもしれない」と添える。
- run の `[job]` は、case から作る run では case の `[job]`、`new --from RUN`（`--continue` 含む）
  では **元 run の `[job]`** を引き継ぐ。`--job k=v` で個別に上書きし（`[job]` の key のみ）、
  `--job-from-case` で case の値に戻す。資源の変更に case の編集を要しない。作成時に、元 run
  （または case）に対する params と資源の差分を表示する。
- **variation は case ではなく run で表現する。** 「同じ物理設定で 1 つの値だけ変える」
  ために新しい case を作らない。`new CASE --set`、`new --from RUN --set`、`sweep` を使う。
  `case new --from CASE` は、base 入力ファイルの構造そのものが変わるときだけ使う。
  この規約は `AGENTS.md` と `runops-create-run` skill に明記する（§10）。

---

## 6. run directory と manifest.toml

### 6.1 directory

```text
<run_dir>/
  manifest.toml
  notes.md               # 任意。run 固有の自由記述（§9）
  input/                 # 凍結済み入力。作成後は変更しない
  submit/
    job.sh
    sbatch.log           # 投入時の stdout/stderr（追記）
    exit.<job_id>        # job.sh が終了時に書く exit code、開始・終了時刻、stage（TOML）
  work/                  # simulator の出力。cwd はここ
  analysis/
    summary.json         # runo summarize の出力
```

v1 の `status/` directory は廃止する。状態は manifest のみが持つ。

### 6.2 manifest.toml

```toml
schema = 2

[run]
id = "R20261015-0003"
label = "wc0147_phi45"            # directory 名の suffix。空でもよい
status = "completed"              # §6.3
created_at = "2026-10-15T10:30:00+09:00"
why = "wc を 0.147 にしたときの sheath 厚みを確認"
scratch = false
expires_at = ""                   # scratch の場合のみ。ISO 8601
pinned = false
tags = ["sheath", "2d"]
superseded_by = []               # archive --superseded-by で記録した置き換え先の run id

[path]
run_dir = "runs/flat_surface/R20261015-0003--wc0147_phi45"   # project root 相対。絶対 path は書かない
archived_from = ""                # archive 時に元の run_dir を記録
archived_at = ""

[origin]
case = "flat_surface"
sweep = ""                        # sweep label。単発 run は空
parent_run = ""                   # --from RUN で派生した場合の source
case_input_hash = "sha256:..."    # 作成時の case の base 入力ファイルの hash
created_by = "agent"              # "human" | "agent" | 任意文字列

[simulator]
name = "emses"
adapter = "emses"
adapter_source = "entry-point"    # "entry-point" | "project-local" | "builtin"
adapter_version = "4.19.0"
build_dir = ""                    # local_source の場合 .runops/build/<sim>-<commit>
executable = "/path/.venv/bin/mpiemses3D"
resolver_mode = "package"
package_version = "1.2.3"
exe_hash = "sha256:..."
git_commit = ""                   # local_source の場合
git_dirty = false

[launcher]
name = "srun"

[job]
scheduler = "slurm"
job_id = "12345"                  # 最新 attempt の job id
partition = "gr20001a"
nodes = 1
ntasks = 800
walltime = "120:00:00"
submitted_at = "2026-10-15T10:31:00+09:00"
finished_at = ""
last_slurm_state = "COMPLETED"
attempt = 1                       # retry で +1
exit_code = "0"                   # sacct の ExitCode、無ければ exit record の値

[[job.attempts]]                  # submit のたびに追記。retry の履歴を残す
attempt = 1
job_id = "12345"
partition = "gr20001a"
submitted_at = "2026-10-15T10:31:00+09:00"
started_at = ""                   # exit record から
finished_at = ""
slurm_state = "COMPLETED"
exit_code = 0                     # exit record から
exe_hash = "sha256:..."           # submit 時点の executable の hash
elapsed = "15:42:10"              # sacct の Elapsed、無ければ exit record の開始・終了から
cancel_reason = ""                # cancel --why の理由。retry はこれがあれば確認を取る

[params]
"tmgrid.nx" = 4000
"plasma.wc" = 0.147
"plasma.phiz" = 45.0

[variation]
changed_keys = ["plasma.wc", "plasma.phiz"]   # case の params との差分 key
job_changed_keys = ["walltime"]                # case の [job] との差分 key（--job / 元 run から）

[identity]
input_hash = "sha256:..."         # input/ 配下全ファイルの content hash

[storage]
work_purged_at = ""               # tidy --purge-work の記録

[[notes]]
at = "2026-10-15T12:00:00+09:00"
by = "agent"
text = "初期 sheath が形成されるまで 2e4 step かかった"
```

規則:

- `manifest.toml` は runops だけが書く。ユーザーと agent は直接編集しない
  （`notes.md` は自由に編集してよい）。
- v1 の `[intent]`、`[curation]`、`[storage].tier/form/retention_class`、
  `[identity]` の `input_hash` 以外、`[classification]` は廃止する。
- `[params]` は case の `[params]` に `--set` を適用した **最終値** を持つ。
  v1 の `[params_snapshot]` と同じ意味。
- 書き込みは tmp ファイルに書いて `os.replace` で atomic に行う。

### 6.3 状態

```text
created ──submit──▶ submitted ──(slurm)──▶ running ──▶ completed
   │                   │                       │   └──▶ failed
   │                   └───cancel──────────────┴──────▶ cancelled
   │
   └────────────── archive ─────────────────────────▶ archived
                   (created / completed / failed / cancelled から)
```

- `retry` は `failed` / `cancelled` を `created` に戻し `job.attempt` を +1 する。
  `work/` は消さない（retry 前に `tidy --purge-work` で明示的に消せる）。
- `restore` は `archived` を archive 前の状態に戻す。archive 前の状態は
  `[path].archived_from` とは別に `[run].status_before_archive` に保存する。
- `sync` が terminal 遷移（completed / failed）を確定するとき、adapter の
  `detect_status()` を呼ぶ。Slurm が `COMPLETED` でも adapter が `failed` を返せば
  `failed` にする。Slurm が `FAILED` なら adapter の結果にかかわらず `failed`。
- `sync` は対象 run の job id をまとめて 1 回の `squeue --jobs=...` で問い合わせ、そこに無い
  job だけを 1 回の `sacct --jobs=...` で引く。`tidy` の `orphan-job` 判定も同じ。
  scheduler への問い合わせ回数は run 数に依存しない。
  runops が対応づけていない Slurm 状態の job は状態を変えずに `last_slurm_state` だけ残し、
  他の run の更新は続ける。
- job.sh は program 終了時に `submit/exit.<job_id>`（`exit_code`、`started_at`、`finished_at`、
  `hostname`、`stage = "run"`）を書く。program より前の準備（`module load`、`export`、`cd`、venv、
  `setup_commands`、`pre_commands`、adapter の `job_prelude`）は `set -e` で実行し、失敗したら
  program を起動せずに終了して、その exit code と `stage = "setup"` を記録する。
  `post_commands` の失敗は記録する exit code を変えない。squeue にも sacct にも無い job は、この file があれば
  `exit_code = 0` のとき adapter の判定（既定 completed）、それ以外は `failed` にする。
  file が無ければ adapter の判定に従い、`unknown` なら `failed`。
- `submit` は manifest に記録された executable を hash し直し、attempt に `exe_hash` を残す。
  作成時の `[simulator].exe_hash` と違えば warning を出す（拒否しない）。
- `new --from RUN` は case の base 入力ファイルが source の作成時（`[origin].case_input_hash`）から
  変わっていれば warning を出す（拒否しない）。
- `submit`、`cancel`、`retry`、`sync` は `.runops/run.lock` の中で manifest を読み直してから
  状態を確認・更新する。同じ run を 2 回指定しても、複数の process から同時に投入しても sbatch は 1 回。
- `new` / `sweep --apply` は `identity.input_hash` が既存 run と一致するとき warning を出す
  （同じ executable なら「結果は同一のはず」、違えば「executable が違う」）。作成は拒否しない。
- `purged` state は廃止。`work/` の削除は `[storage].work_purged_at` で表す。

---

## 7. CLI

### 7.1 共通規則

- script 名は `runo`（`runops` alias は維持する）。
- command は **flat** に置く。group は `case` のみ。
- すべての command は project root を `runops.toml` を上方向に探して特定する。
  見つからなければ exit code 2 でエラー。
- `RUN` 引数は run id、run directory path、または directory 名の一意な部分文字列を受け付ける。
  複数一致は exit code 2 でエラーにし候補を表示する。
- path で与える `RUN` と `DIR`（`submit --all`、`list`、`archive`）は、この project の `runs/`
  配下に限る。別 project の path は exit code 2 で拒否する。run id は project ごとの空間なので、
  同じ id が別 project にあっても cwd の project の run を指す。
- 一覧系 command は `--json` を持ち、agent が機械可読に読める。`new` と `sweep --apply` の
  `--json` は作成した run の同じ summary を返す。summary には `params`、`changed_keys`、
  `parent_run`、`exe_hash`、`input_hash` を含め、run 同士の比較に別 command を要らなくする。
  walltime の根拠として `walltime`、最新 attempt の `elapsed`、`walltime_used`（elapsed / walltime）、
  `slurm_state`（`TIMEOUT` など）も含める。
- 破壊的 command（`cancel`、`delete`、`tidy --apply`、`archive`）は対象を表示して
  確認を取る。`-y/--yes` で省略。
- exit code: 0 成功、1 対象 run の実行時エラー（例: sbatch 失敗）、2 使用方法・設定エラー。

### 7.2 run の発見

- `runs/` 配下（`_archive/` を含む）を再帰的に走査し `manifest.toml` を集める。
  `.runops/index.toml` に `run_id -> run_dir` の cache を持ち、manifest が cache の
  path に無ければ再走査して cache を更新する。cache は常に再生成可能で、
  壊れていても動作に影響しない。
- 走査対象は `runs/` のみ。project 外や `runs/` 外の run は扱わない。

### 7.3 command 一覧

| command | 効果 |
|---|---|
| `runo init [SIM...] [--site kudpc\|standard] [--no-install] [-y]` | `runops.toml`、`cases/`、`runs/`、`LOG.md`、`AGENTS.md`、`.venv` を作る。SIM ごとに adapter package を `.venv` に install し、skill を展開する（§8）。端末から引数なしで実行すると site と simulator を尋ねる。`--site` が無ければ host 名から推定する（KUDPC のログインノードなら `kudpc`） |
| `runo doctor [--json]` | `runops.toml` の妥当性、adapter の import 可否、executable の存在、`sbatch` の有無、skill の鮮度を検査 |
| `runo update [--skills-only] [-y]` | adapter package を upgrade し、skill を再展開する |
| `runo build SIM [--force]` | `local_source` simulator を `.runops/build/` に build する（§4.1） |
| `runo context [--json]` | agent 向け現在地。project 名、simulator、active run 数、直近 run 5 件、scratch 期限切れ数、`LOG.md` 末尾 20 行。配置した runops skill が install 済みの runops より古ければ `runo update --skills-only` を促す warning |
| `runo case new NAME --simulator SIM [--from CASE]` | case をスキャフォールド。adapter の `case_template()` を展開 |
| `runo case list` | case 一覧 |
| `runo new CASE [--why TEXT] [--label L] [--set k=v]... [--job k=v]... [--tag T]... [--scratch] [--dest DIR] [--submit] [--created-by WHO] [--json]` | 単発 run を作る |
| `runo new --from RUN [--why] [--set k=v]... [--job k=v]... [--job-from-case] [--continue] [--submit]` | 既存 run の params と `[job]` から派生 run を作る（§5）。`--continue` は adapter が `extend_inputs()` を実装する場合のみ有効（§8.1） |
| `runo sweep CASE --set k=v1,v2,... [--set ...] [--names KEY=n1,n2,...]... [--job k=v]... [--label L] [--dest DIR] [--why TEXT] [--apply] [--submit] [--limit N] [--json]` | 直積の候補を表示する。`--apply` で生成。`--submit` は `--apply` と同時のみ有効 |
| `runo submit RUN... [--partition P] [--qos Q] [--afterok JOBID] [-y]` | job.sh を生成して sbatch。`created` 以外は拒否 |
| `runo submit --all [DIR] [-y]` | DIR 配下の `created` run をすべて投入。件数と概算 core-hours を表示して確認 |
| `runo cancel RUN... [--why TEXT] [-y]` | scancel して sync。`--why` は `cancelled: ...` の note として残す |
| `runo retry RUN [--submit] [-y]` | `failed`/`cancelled` を `created` に戻す。直近の cancel に `--why` があれば理由を示して確認を取る |
| `runo status [RUN...] [--json]` | manifest の状態を表示。Slurm を呼ばない |
| `runo sync [RUN...] [--json]` | squeue/sacct で状態を更新。引数なしは `submitted`/`running` 全件 |
| `runo log RUN [--err] [-n N] [-f]` | 最新 job の stdout/stderr を表示。`-f` は tail -f |
| `runo list [PATH] [--all] [--since 30d] [--case C] [--sweep L] [--status S]... [--tag T]... [--scratch] [--archived] [--json]` | run 一覧（§7.4） |
| `runo note RUN [TEXT] [--by WHO]` | TEXT があれば `[[notes]]` に追記、なければ notes と `notes.md` を表示 |
| `runo pin RUN [--off] [--reason TEXT]` | `run.pinned` を切り替える。pinned は `list` に常に出て、`tidy` / `delete` の対象外 |
| `runo summarize RUN... [--force]` | adapter の `summarize()` を呼び `analysis/summary.json` を書く。既存があれば `--force` なしではスキップ |
| `runo mv RUN... [--dest DIR] [--label L] [--why TEXT]` | run を `runs/` 配下で改名・移動する。id、入力、履歴は変えない（§7.7） |
| `runo archive RUN\|DIR... [--superseded-by RUN\|DIR --why TEXT] [-y]` / `runo archive --older-than 90d [-y]` | `runs/_archive/<元の相対 path>` に移動して `archived` にする。対象は created と終端の run（created は job を持たないため）。移動前に全対象を検査し、指定した RUN が対象外なら何も動かさない。DIR は配下の run（系列）を指し、submitted / running と pinned を除いて表示する。created は `--superseded-by` があるときだけ含める。`--superseded-by` は各 run に置き換え先（`parent_run` がその run の置き換え先 run、無ければ指定した全 run）を `run.superseded_by` に記録し、`--why` を note に残す |
| `runo restore RUN` | archive 前の場所に戻す。既に何かあれば拒否 |
| `runo delete RUN... [-y]` | directory を削除。`created`/`failed`/`cancelled`/scratch のみ。`pinned` は拒否 |
| `runo tidy [--apply] [--only KIND] [--older-than AGE] [--purge-work RUN...] [--json]` | 整理候補を表示する（§7.5）。`--apply` で実行 |
| `runo migrate-v1 [--dry-run] [--apply-delete-test-runs] [-y]` | v1 project を v2 layout に変換する（§11） |
| `runo --version` | version 表示 |

### 7.4 `list` の規則

- 既定で表示するのは次の **どれか** を満たす run: `status` が `created`/`submitted`/`running`、
  `created_at` が `defaults.list_since_days` 以内、`pinned = true`。
- 既定で表示しない: scratch run、archived run、上記以外の古い terminal run。
- `--all` は scratch と archived 以外をすべて表示。`--scratch`、`--archived` は
  それぞれを **追加** する。
- 表示列: id、status、label、case、sweep、created（相対時刻）、最新 note の先頭 60 文字、`why`。
- sort は `created_at` 降順。
- `PATH` を与えた場合はその directory 配下に限定する。

### 7.5 `tidy` の規則

`tidy` は候補を 4 種に分けて表示する。`--apply` はすべてを実行し、
`--apply --only KIND` で絞れる。

| kind | 条件 | 動作 |
|---|---|---|
| `expired-scratch` | `scratch = true` かつ `expires_at` を過ぎ、`pinned = false`、archived でない | delete |
| `stale-failed` | `failed`/`cancelled` で `defaults.tidy_failed_days`（既定 30）日より古く、note も `why` も空 | delete |
| `old-completed` | `completed` で `defaults.tidy_archive_days`（既定 90）日より古く、`pinned = false` | archive |
| `orphan-job` | `submitted`/`running` だが squeue/sacct に job が無い | sync（state 確定） |
| `unused-build` | `.runops/build/*` のうち、非 archived run の manifest から参照されないもの | delete |

- `--older-than AGE`（例 `14d`）はその回だけ、上の 2 つの日数をどちらもこの値で置き換える。
- `--purge-work RUN...` は指定 run の `work/` の中身を削除し `work_purged_at` を記録する。
  adapter が `keep_patterns()` を返す場合、一致するファイルは残す。`completed` 以外は拒否。
  adapter を読み込めない（残すファイルを判定できない）ときは何も消さずにエラーにする。
- `tidy` は receipt や tombstone を作らない。失敗したら error を出して止まる。
  部分実行された結果は各 run の manifest にそのまま残る（再実行で続きから処理できる）。

### 7.6 `sweep` の規則

- `--set k=v1,v2` を複数与えた場合は直積。同じ key を 2 回与えたらエラー。
- 候補表示は `p0001`、各 key の値、label 案、合計件数、概算 core-hours
  （`nodes * ntasks * walltime` の合計）を出す。
- `--apply` は候補全件を生成する。部分選択は `--limit N`（先頭 N 件）だけ。
  より細かい選択が要るなら `runo new --set` を使う。
- 生成先は `runs/<case>/<sweep_label>/<run_id>--<label>/`。
  `sweep_label` 省略時は `sweep-<YYYYMMDD>-<NN>`。
- label は changed_keys から自動生成する（`wc0.147_phiz45`）。長さ上限は `defaults.label_max_length`（既定 48 文字）。
  key の短縮 alias は case.toml の `[naming.aliases]` で指定できる（v1 と同じ）。
- `--names KEY=n1,n2,...` は掃引する KEY の各値に短い名前を付け、label ではその key の
  alias + 値の代わりに名前を使う（構造化した配列を 1 軸にしたとき `wh0`、`wh1` のようにする）。
  名前の数は値の数と同じで、重複は不可。入力や params には何も足さない。
- `--dest DIR` は sweep directory の親を変える（既定 `runs/<case>`）。系列で共通の条件を
  `--label` に、各点の違いを label に置く命名を作れる。

### 7.7 `mv` の規則

- `runo mv RUN... --dest DIR` は run を DIR（`runs/` 配下、`_archive` と既存 run の外）へ移す。
  `--label L` は directory 名の suffix と `run.label` を変える（1 run のときだけ。`''` で外す）。
- run id、`input/`、`input_hash`、`[origin]`（case、sweep、parent_run）、notes、投入履歴は変えない。
  `[path].run_dir` と index を更新し、移動元と `--why` を `[[notes]]` に追記する。
- 対象は `created`、`completed`、`failed`、`cancelled`。`submitted` / `running` は拒否する
  （Slurm が run directory の絶対 path を持つ）。`archived` は `restore` を使う。
- 既存 path は上書きしない（`move_noreplace`）。`created` の run は job.sh を作り直す。
- 複数 run は `run.lock` を 1 回取り、全対象の状態と移動先を検査してから移す。1 件でも拒否されれば
  どれも動かさない。移動中に filesystem の error が起きたら止まり、移し終えた run id を error に示す
  （exit code 1）。`archive RUN...` も同じ手順で移す。
- 手で `mv` しても run は id で見つかるが、`run.label` と `[path].run_dir` が古いまま残る。

---

## 8. adapter と simulator package 連携

### 8.1 adapter 契約

```python
class SimulatorAdapter(ABC):
    name: str                                    # entry point 名と一致

    # --- 必須 ---
    @abstractmethod
    def render_inputs(self, params: dict[str, Any], run_dir: Path) -> list[str]:
        """input/ 配下の base file に params を適用し、書いたファイル名を返す。"""

    @abstractmethod
    def build_command(self, runtime: RuntimeInfo, run_dir: Path) -> list[str]:
        """launcher の後ろに置く program 部分の argv。job の cwd は run_dir。"""

    @abstractmethod
    def detect_status(self, run_dir: Path) -> Literal["completed", "failed", "unknown"]:
        """work/ を見て完了判定する。"""

    # --- 任意（既定実装あり） ---
    def case_template(self) -> dict[str, str]: return {}        # file名 -> 内容
    def pip_packages(self) -> list[str]: return []
    def resolve_runtime(self, sim_config: dict, venv: Path) -> RuntimeInfo: ...  # 既定: executable を .venv/bin → PATH の順で探す
    def collect_provenance(self, runtime: RuntimeInfo) -> dict[str, Any]: ...    # 既定: exe_hash, package_version
    def validate_params(self, params: dict) -> list[str]: return []              # warning 文字列
    def summarize(self, run_dir: Path) -> dict[str, Any]: return {}
    def keep_patterns(self) -> list[str]: return []              # purge-work で残す glob
    def extend_inputs(self, src_run: Path, run_dir: Path, params: dict) -> list[str]:
        raise NotImplementedError                                # --continue 対応
    def agent_context_dir(self) -> Path | None: return None      # §8.2
    def configure(self, sim_config: dict) -> None: ...           # runops.toml の [simulators.X] を受け取る
    def job_prelude(self, run_dir: Path) -> list[str]: return [] # job.sh で実行直前に置く shell 行
```

- job.sh は run_dir へ `cd` してから実行する（v1 と同じ。v1 adapter の path 規約
  `input/...`、`work/latest` をそのまま使える）。Slurm の stdout / stderr は `work/` に出る
  （`sbatch --chdir=<run_dir>/work`）。

- `render_inputs()` は **dotted key を入力ファイルの階層に写す** ことを要件とする。
  例: `"plasma.wc" = 0.147` は `plasma.toml` の `[plasma] wc = 0.147`、
  `"boundary.radius" = 7e-6` は `beach.toml` の `[boundary] radius = 7e-6`。
  base 入力が TOML の adapter は、runops が提供する helper
  `runops.adapters.toml_override(path, params)` をそのまま使ってよい。
  これにより case の `[params]` が空でも `--set` で variation を作れる。
- v1 の `interactive_config`、`doc_repos`、`knowledge_sources`、`codex_plugins`、
  `parameter_schema`、`default_plot_recipes`、`required_outputs`、`probe_readiness`、
  `agent_guide`、`build_version_capture_commands` は契約から外す。
- runops 本体に simulator 固有の adapter を **同梱しない**。同梱するのは `generic`（§8.4）だけ。
  v1 の `adapters/contrib/emses`、`adapters/contrib/beach` は §8.5 の手順で外に出す。
- adapter は Python class だが、simulator package が `runops` を import する必要は無い。
  `SimulatorAdapter` は `typing.Protocol` として定義し、必須 3 method と `name` 属性を持つ
  class なら何でも受け付ける。既定実装が欲しい場合だけ `runops.adapters.base.SimulatorAdapter`
  を継承すればよい（その場合 simulator package の optional extra `[runops]` に runops を書く）。
- adapter 名 `X` の解決順:
  1. `runops.adapters` entry point group に `X` があればそれ
  2. project の `adapters/X.py` があればそれを import し、`Adapter` という名前の class を使う
     （project ローカル adapter。simulator repo を触れない、または patched build だけを
     使う場合の正規経路）
  3. `X == "generic"` なら同梱 generic
  4. どれも無ければ exit code 2 で、`pip install <package>` か `adapters/X.py` の作成を案内
- `doctor` は各 simulator の adapter がどの経路で解決されたかを表示する。
- `RuntimeInfo` は `executable: Path`、`package_version: str`、`exe_hash: str`、
  `git_commit: str`、`git_dirty: bool`、`env: dict[str, str]` を持つ dataclass。

### 8.2 agent context の展開

simulator package は agent 向けの skill と reference を package data として同梱し、
adapter の `agent_context_dir()` でその directory を返す。directory 構成は次を期待する。

```text
<agent_context_dir>/
  skills/
    <skill-name>/
      SKILL.md
      ...
  references/
    *.md
```

runops は `init` と `update` で次を行う。

1. `agent_context_dir()` が返す `skills/*` を `.agents/skills/<skill-name>/` と
   `.claude/skills/<skill-name>/` にコピーする。skill 名の名前空間は package 側が持つ
   （例: `mpiemses3d-input-review`）。`runops-` で始まる名前は予約されており展開しない。
2. `references/` を `.agents/skills/<adapter>-references/` にコピーし、
   `SKILL.md` が無ければ reference 一覧を列挙した `SKILL.md` を生成する。
   展開した skill の `../../references/`（package 内の配置での参照）は
   `../<adapter>-references/` に書き換える。
3. 展開先には `.managed-by-runops` marker を置く。marker のある directory は
   `update` 時に **無条件で上書き** する。marker の無い同名 directory は触らず warning。
4. `.runops/skills.lock` に adapter 名、package version、展開した directory、content hash を記録する。

`doctor` は lock の package version と現在 install されている version を比較し、
差があれば `runo update --skills-only` を提案する。展開済み skill の相対リンクで
存在しない file を指すものも報告する。

既存の simulator repo（MPIEMSES3D、emout、BEACH）は `plugins/<name>-context/` に
`skills/` と `references/` を既に持つ。各 package 側で必要な変更は
「その directory を package data に含め、adapter から path を返す」だけである。
**runops 側に simulator の知識をコピーして保持しない。**

### 8.3 runops 自身の skill

runops は次の 5 skill だけを同梱し、simulator skill と同じ仕組みで展開する。
利用者が覚えるコマンドは `runo init` だけとし、それ以外（simulator の追加、更新、v1 移行を含む）は
エージェントへの依頼で行う。
各 SKILL.md は 60 行以内に収める。

| skill | 内容 |
|---|---|
| `runops-create-run` | `new` / `sweep` の使い方。`--why` を必ず書く、scratch の使い分け |
| `runops-check-status` | `sync` → `list` → `log` の順。失敗時の `retry` と `tidy --purge-work` |
| `runops-tidy` | `tidy` を定期的に実行する判断基準。pin の使い方 |
| `runops-reference` | command 一覧（§7.3 の表をそのまま載せる） |
| `runops-maintain` | simulator の追加、runops と simulator package の更新、`migrate-v1`、`doctor` の読み方 |

### 8.4 generic adapter

simulator package が無くても使えるよう `generic` adapter を同梱する。

- `render_inputs`: `cases/<name>/` の base file を Jinja2 template として `params` で render する。
- `build_command`: `simulators.<name>.command` に書かれた文字列を `shlex.split` する。
- `detect_status`: `simulators.<name>.success_marker` を設定した場合だけ `work/<marker>` の
  有無で `completed` / `failed` を返す。未設定なら `unknown` を返し、Slurm の状態で決まる。


### 8.5 既存 adapter の移行

v1 の `emses` / `beach` adapter は次の順で runops 本体から出す。

1. v2 契約（§8.1）に移植した `emses.py` と `beach.py` を `src/runops/legacy_adapters/` に
   置く。registry には登録しない。`migrate-v1` が実行時に読むため package に含める。
2. `migrate-v1` は project の `simulators.*.adapter` が `emses` / `beach` のとき、
   対応する file を project の `adapters/` にコピーする（既にあれば触らない）。
   これで simulator repo の対応を待たずに旧 project が v2 で動く。`runo init` も、
   `emses` / `beach` の adapter が entry point で見つからないときは同じ file を置く。
3. MPIEMSES3D と BEACH の Python package に entry point と `agent_context_dir()` を追加したら、
   `legacy_adapters/` の該当 file を削除する。project ローカルの copy は entry point が
   見つかると使われなくなる（解決順 1 が優先）ので、ユーザーが消せばよい。
---

## 9. ノート

置き場所は 3 つに固定し、runops はどれも「管理」しない（schema、budget、rotation、
seal、index を持たない）。

| 種類 | 置き場所 | 寿命 |
|---|---|---|
| run 固有の観察 | run 内の `notes.md`（自由記述）と manifest の `[[notes]]`（`runo note` 経由、timestamp 付き） | run と一緒に archive / delete される |
| 時系列の判断・経過 | `LOG.md` 1 ファイル。日付見出しで追記専用 | project と同じ |
| 永続的な知見（式、手法、落とし穴） | `notes/<topic>.md`。1 topic 1 file、flat、frontmatter 不要 | project と同じ。古くなったら人が消す |

- runops は `init` で `LOG.md` と `notes/README.md` の雛形を作る以外、これらを読み書きしない
  （`context` が `LOG.md` 末尾と `notes/` の file 名一覧を表示するだけ）。
- agent harness（`AGENTS.md`）は次を指示する。
  - run に関する観察は `runo note RUN "..."` に書く
  - 複数 run にまたがる結論と次の判断は `LOG.md` に日付付きで追記する
  - 再利用する式・手法・環境の落とし穴は `notes/<topic>.md` に書く。既存 file があれば追記し、
    似た topic の file を増やさない
  - それ以外の場所（`research/`、`analysis/*.md`、`runs/` 直下など）に note file を作らない
- v1 の `research/results/`、`.runops/insights/`、`research/archive/legacy/` は移行時に
  `notes/legacy/` 配下へ **移動せず** そのまま残し、`notes/README.md` から path を案内する（§11）。

---

## 10. harness 生成

`init` が生成する agent 向けファイルは次だけ。

- `AGENTS.md`: 120 行以内。project 名、simulator、§7.3 の command 表、作業の進め方、
  §9 のノート規約、展開済み skill の一覧。作業の進め方は次の 5 項目で、それぞれ「何をするか」と
  短い理由で書く（禁止事項の列挙にしない）。依頼が操作の範囲を決める、submit 前に対象と資源量を
  示して確認を取る、操作対象は起動した project の run と job、run の変更は `runo` を通す
  （variation は case ではなく run、§5）、理由を残す（`--why`、`cancel --why`、`--superseded-by`）。
- skill は手順を書き、AGENTS.md の方針を繰り返さない。
- harness file は project root にだけ置く。`runs/` や `cases/` 配下には生成しない。
- `CLAUDE.md`: `@AGENTS.md` の 1 行。
- `.agents/skills/`、`.claude/skills/`: §8.2、§8.3 の展開結果。

`update` は `AGENTS.md` の runops 管理 block（`<!-- runops:begin -->` 〜
`<!-- runops:end -->`）だけを再生成し、block 外のユーザー記述を保持する。

---

## 11. v1 からの移行

`runo migrate-v1 [--dry-run]` は v1 project を次のように変換する。一回限りの command で、
framework 化しない。

| v1 | v2 |
|---|---|
| `simulators.toml` + `launchers.toml` + `site.toml` | `runops.toml` に統合。`codex_plugins` は捨てる。`[site.simulators.X].modules` は `[simulators.X].modules` に入れる。launcher の `type` は `kind` にする |
| `cases/<sim>/<name>/` | `cases/<name>/` に移動。衝突時は `<sim>-<name>` |
| `[classification]` | `case.tags` / `run.tags` に `model`、`submodel`、`tags` を平坦化 |
| manifest `[intent].purpose` | `run.why` |
| manifest `[storage].pinned` | `run.pinned` |
| manifest `[params_snapshot]` | `[params]` |
| manifest `status = purged` | `status = archived` + `storage.work_purged_at = <archived_at>` |
| manifest `[path].bundle_archived_from` | `[path].archived_from` |
| manifest `[path].run_dir`（絶対 path） | project root 相対に変換。project 外を指す場合は warning を出し現在の実 path で上書き |
| manifest `[job].queue`、`last_slurm_state`、`[[job.attempts]]` | `queue` は捨てる。`last_slurm_state` と `[[job.attempts]]` はそのまま |
| `[simulators.<name>]` の `executable` が `.runops/work/<name>-<hash>/bin/...` | `.runops/work/<dir>` を `.runops/build/<dir>` に移動し path を書き換える。移動できない場合は `local_executable` のまま残す |
| `runs/**/survey.toml` | 同じ directory 配下の run の `origin.sweep` が空なら `survey.id`（無ければ directory 名）を補う。file 自体は残す |
| `runs/_archive/` 配下の run（v1 の bundle archive を含む） | `status = archived`、`archived_from` は `_archive/` を外した path |
| `runs/AGENTS.md`、`runs/CLAUDE.md`、`cases/**/AGENTS.md` など root 以外の harness file | `.runops/v1-backup/<stamp>/` へ移動 |
| `.runops/test-runs/T*/` | 削除候補として表示（`--apply-delete-test-runs` で削除） |
| `experiments/`、`research/`、`.runops/insights/`、`.runops/knowledge/`、`refs/`、`materials/`、`analysis/`、`harness-feedback/`、`.harnessops/` | 触らない。`notes/README.md` と `LOG.md` 末尾に「v1 の資料は以下に残る」と path 一覧を追記 |
| `campaign.toml`、`SITE.md`、`.harness/`、`.runops/facts.toml`、`.runops/environment.toml`、`.runops/harness.lock` | 触らない（git 履歴で消せる）。`doctor` が「v1 の残骸」として列挙する |
| v1 の `runops.toml`、`AGENTS.md`、`CLAUDE.md`、`.codex/`、`.claude/skills/runops-*`、`.agents/skills/runops-*` | `.runops/v1-backup/<stamp>/` へ移動し v2 の harness を生成 |
| 各 run の v1 manifest | `manifest.v1.toml` として同じ run directory に残す |

- 変換後の manifest は `schema = 2`。v2 の runops は `schema` が無い、または `1` の
  manifest を読んだら `migrate-v1` を案内して exit code 2。
- run directory の物理的な移動は行わない。`runs/sheath/wc_scan/R...` のような v1 の
  配置はそのまま読める（§3 の規約通り）。

---

## 12. 実装計画（完了）

### 12.1 進め方

- v1 を in-place で削るのではなく、`src/runops/` を **新規に書き直す**。
  v1 のコードは参照用に `git` 履歴に残す。branch は `v2`、merge 後 `2.0.0` を tag する。
- 再利用してよい v1 モジュール（読んで必要部分だけ移植する。そのままコピーしない）:
  - `core/run/`、`core/state.py`（RunState、manifest 読み書き）
  - `slurm/submit.py`、`slurm/query.py`（runner 注入による mock 可能な構造を維持する）
  - `launchers/`（srun / mpirun / mpiexec）
  - `jobgen/generator.py`（job.sh 生成、`resource_style = rsc` 対応）
  - `adapters/base.py`、`adapters/registry.py`（entry point 発見）、`adapters/generic.py`
  - `adapters/_runtime.py`（`local_source` の build と exe hash）
  - `application/run_creation/` の params merge と label 生成、`core/survey/` の直積展開
- 実在の v1 project（`/home/b/b36291/large1/project_dust_release`、
  `/home/b/b36291/large1/ion_depression`）は読み取り専用の参照に使う。
  **これらの directory を変更しない。** `migrate-v1` の検証は
  `tests/fixtures/v1-project/` に縮小した copy を作って行う（manifest と case.toml を
  数件ずつ、`work/` は空）。
- 新規に書く: `runops.toml` loader、`list` / `tidy` / `note` / `context`、
  agent context 展開（§8.2）、`migrate-v1`、harness 生成（§10）。
- 捨てる（移植しない）: `application/actions/admin.py`、`bundle_archive.py`、
  `test_attempts.py`、`triage.py`、`experiments.py`、`research/`、`publication/`、
  `analysis/story/`、`gateway/plugins/`、`harness/`、`mcp/`、`core/demo/`、
  `core/knowledge*`、`operator/migrations/`、`cli/update_harness.py`、
  `templates/skills/`（4 つの runops skill は新規に書く）、`templates/harness/`、
  `adapters/contrib/`（emses / beach は §8.5 の手順で `src/runops/legacy_adapters/` に移植し、
  package からは外す）。

### 12.2 module 構成

```text
src/runops/
  __init__.py
  cli.py              # Typer app。command ごとの関数は薄く、ops.* を呼ぶだけ
  config.py           # runops.toml の読み込みと検証
  project.py          # project root 探索、run 発見、index cache
  manifest.py         # Manifest（dict を保持）、読み書き、状態遷移
  case.py             # case.toml、label 生成、core-hours
  runtime.py          # executable 解決、local_source の build cache
  util.py             # TOML I/O、atomic write、move_noreplace
  errors.py           # exit code 付き例外
  ops/
    common.py         # simulator / adapter の解決 helper
    create.py         # new / sweep / case new
    submit.py         # submit / cancel / retry、job.sh 書き出し
    sync.py           # sync / status / log
    listing.py        # list の選択規則
    tidy.py           # tidy / archive / restore / delete / purge-work
    notes.py          # note / context / summarize
    setup.py          # init / doctor / update
    skills.py         # agent context の展開、skills.lock
    migrate.py        # migrate-v1
  adapters/
    base.py           # Protocol、RuntimeInfo、toml_override、set_dotted
    registry.py
    generic.py
  legacy_adapters/    # v1 emses / beach の移植（migrate-v1 がコピー）
  launchers.py        # srun / mpirun / mpiexec / none
  jobgen.py
  slurm.py            # sbatch / scancel / squeue / sacct（runner 注入）
  harness.py          # AGENTS.md / CLAUDE.md 生成
  skills/             # runops 自身の 4 skill（package data）
```

- `cli.py` は入力検証、確認 prompt、表示だけを持つ。business logic は `ops/` に置き、
  CLI を通さず直接テストできるようにする。
- `ops/` は `slurm.py` を直接 import せず、関数引数で runner を受け取る
  （v1 の `CommandResult` / `_default_runner` の形を踏襲）。

### 12.3 phase

1. **骨格**: `config`、`project`、`manifest`、`cli` の `init` / `doctor` / `case new` /
   `new` / `status` / `list`。generic adapter。job.sh 生成なし。
2. **投入**: `jobgen`、`launchers`、`slurm`、`build`（local_source）、`submit` / `sync` / `cancel` / `retry` / `log`。
3. **整理**: `note` / `context` / `tidy` / `archive` / `restore` / `delete` / `summarize` / `sweep` / `new --from`。
4. **連携**: `skills.py`、`harness.py`、`update`。MPIEMSES3D 側に entry point と
   `agent_context_dir` を足して end-to-end 確認。
5. **移行**: `migrate-v1`。実在の v1 project で dry-run → apply を確認。

各 phase の終わりに `uv run pytest`、`ruff check`、`mypy src/` を通す。

---

## 13. 規模目標と受け入れ基準

### 13.1 規模

| 項目 | 目標 |
|---|---|
| `src/runops/` の行数（skill の md を除く） | 8,000 行以下 |
| CLI command 数（`case new` / `case list` を含む。同じ command の option 違いは数えない） | 25 以下。§7.3 の表の distinct command は 24 |
| ユーザーが編集する TOML | `runops.toml`、`case.toml` の 2 種 |
| runops が書く TOML | `manifest.toml`、`.runops/skills.lock`、`.runops/index.toml` の 3 種 |
| 依存 | `typer`、`rich`、`tomli-w`、`tomlkit`、`jinja2`、`packaging`（`mcp` を外す） |
| テスト実行時間 | 60 秒以内（Slurm は全て mock） |

### 13.2 受け入れ基準

以下がすべて pytest で検証されていること。

1. `runo init generic -y` した project で `case new` → `new --why x` → `submit`（mock sbatch）→
   `sync`（mock squeue が COMPLETED）→ `list` が 1 件表示し `status = completed` になる。
2. `new --scratch` した run は `list` 既定で表示されず、`expires_at` を過ぎると
   `tidy` が `expired-scratch` として挙げ、`tidy --apply` で消える。`pinned = true` なら消えない。
3. run directory を `runs/` 配下の別の場所に `mv` しても `runo status RUN_ID` が見つける。
4. `sweep CASE --set a=1,2 --set b=x,y` が 4 候補を表示し directory を作らない。
   `--apply` で 4 run が `runs/<case>/<sweep_label>/` に生成され、各 manifest の
   `variation.changed_keys` が `["a", "b"]` になる。
5. `archive` → `restore` で `run_dir`、`status` が元に戻る。restore 先に directory が
   あれば拒否する。
6. `submit` は `created` 以外を拒否し、`delete` は `running` / `completed` / `pinned` を拒否する。
7. `.venv` に entry point を持つ dummy package を install した状態で `init dummy` が
   adapter を発見し、`agent_context_dir()` の skill が `.agents/skills/dummy-*/` に展開され、
   `skills.lock` に記録される。dummy package の version を上げて `update --skills-only` すると
   marker 付き directory だけが上書きされる。
8. `rsc` と `standard` の両 `resource_style` で生成した job.sh が golden file と一致する。
   golden は MPI 型（`nodes`/`ntasks`、srun）と OpenMP 型（`processes`/`threads`/`cores`、
   `pre_commands` あり）の 2 種を用意する。
8b. `local_source` simulator で `runo new` したとき `.runops/build/<sim>-<commit>/` に
   build が走り（mock build_command）、manifest に `exe_hash` と `git_commit` が入る。
   2 回目は build が走らない。
9. v1 の sample project（`tests/fixtures/v1-project/`）に `migrate-v1 --dry-run` が
   変換計画を表示し、`migrate-v1` 後に `list --all` が v1 の run をすべて表示する。
   fixture の simulator が `beach` なら `adapters/beach.py` がコピーされ、`doctor` が
   「project ローカル」経路で解決したと表示する。
9b. 同名 adapter が entry point と `adapters/X.py` の両方にあるとき entry point が優先される。
   どちらも無く `generic` でもなければ exit code 2 で案内が出る。
10. `manifest.toml` の書き込み途中で例外が起きても元のファイルが壊れない。

### 13.3 ドキュメント

v2 の文書は次の 4 ファイルだけにする。

- `README.md`: 導入と 5 分の tutorial
- `docs/guide.md`: 場面ごとの使い方。エージェントへの頼み方と裏の `runo` コマンドを並べる
- `docs/reference.md`: §4〜§7 を利用者向けに書き直したもの
- `docs/adapter.md`: §8 を simulator package 作者向けに書き直したもの

`SPEC_V2.md` は実装完了時に `SPEC.md` に rename し、v1 の `SPEC.md` と `docs/` は削除する。

---

## 14. 実装時の決定（2026-10-15）

実装と実データ（§1.3 の 2 project のコピー）での検証を通じて、上の本文に反映した決定。

| 項目 | 決定 | 理由 |
|---|---|---|
| job の cwd | run_dir（v1 と同じ）。Slurm log は `work/` | v1 adapter の path 規約と実 project の job.sh をそのまま使える |
| adapter の追加 hook | `configure(sim_config)`、`job_prelude(run_dir)` | generic の `command` 取得と、EMSES の `rm -f *_0000.h5` など v1 の setup command を表す |
| launcher `kind = "none"` | MPI launcher を使わず program を直接実行 | OpenMP のみの BEACH run 用 |
| `runo pin` | command を 1 つ追加（計 23 + `--version`） | `pinned` を立てる手段が本文に無かった |
| `runo mv`、`sweep --names` / `--dest`（2026-10-20） | id を保つ改名・移動を command にする（計 24）。sweep の各点に短い名前を付け、親 directory を選べるようにする | 運用で、投入前に名前を短くするだけで 10 run を `new --from` で作り直し、id が 10 増えた（#110）。構造化配列を 1 軸にすると label に配列が展開された（#111）。未投入 run の入力編集は「入力は作成時に固定」を崩すので見送る |
| walltime の根拠（2026-10-20） | attempt ごとに `elapsed` を記録し、`list` / `status` に `elapsed`、`walltime`、`walltime_used`、`slurm_state` を出す。表では TIMEOUT などを `failed (TIMEOUT)` と示す。似た run の選択と余裕の倍率は skill の指針に置き、runops は推奨値を出さない | 「似た run」の自動判定は外れたときの害が大きい。根拠の数値を見せ、判断はエージェントと人に任せる（#109） |
| generic の `success_marker` | 既定は未設定（Slurm の状態に従う） | 既定 `COMPLETED` だと marker を書かない program が全て failed になる |
| skill 名 | package の skill 名をそのまま使う | MPIEMSES3D の skill は既に `mpiemses3d-` で名前空間がある |
| `new --from RUN` の入力 | case の base file に、source run の params と `--set` を適用 | generic の template と TOML override の両方で同じ結果になる |
| dotted key | `a.b`、`a[0].b`、`a.0.b` を受ける | v1 survey が `species.0.x` 形式を使っていた |
| rename | `renameat2(RENAME_NOREPLACE)`、未対応なら lock 下の存在確認 + `rename` | KUDPC の Lustre は NOREPLACE を EINVAL で拒否する（runhand で判明） |
| `.venv` の entry point 探索 | `site.addsitedir` で `.pth` も処理し、探索前に `importlib.invalidate_caches()` | editable install と、mtime が秒単位の Lustre 上での再インストール直後に対応 |
| migrate の可逆性 | 削除せず `.runops/v1-backup/<stamp>/` と `manifest.v1.toml` に退避 | 実 project の v1 資料を失わない |
| 依頼と操作範囲、観察方針 | AGENTS.md block と `runops-check-status` に記載 | runhand の work policy から取り込み |
| scheduler 問い合わせの一括化 | `sync` / `tidy` は `squeue --jobs=` と `sacct --jobs=` を各 1 回 | run ごとの問い合わせは active run 数に比例して scheduler を叩く。agent は sync を繰り返すので回数を run 数から切り離す |
| job 側の完了証拠 | job.sh が `submit/exit.<job_id>` を書き、`sync` は sacct より先にこれを見る | sacct の保持期間や会計の欠落で completed run が `failed` に倒れていた（row の products、Sumatra の status tag に相当） |
| submit 時の executable hash | attempt ごとに `exe_hash` を記録し、作成時と違えば warning | `runo update` 後の retry が作成時の hash のまま別 binary で走っていた |
| 同一入力の warning | `input_hash`（と `exe_hash`）が一致する既存 run を作成時に知らせる | §1.3 で観察した variation の重複を、ゲート無しで抑える |
| 整理と命名のしきい値 | `[defaults]` に `tidy_failed_days`、`tidy_archive_days`、`label_max_length` を追加。completed の目安は「`--older-than` の 3 倍」をやめて独立の値に | project ごとに計算期間や命名が違い、エージェントに毎回 option を渡させると揃わない |
| `runo init` の対話と site の推定 | 端末から引数なしで実行したときだけ site と simulator を尋ねる。site の既定はホスト名（`camphor*`、`laurel*`、`cinnamon*`、`gardenia*` なら `kudpc`）。プリセット名は `kudpc` とし、`camphor` も同じ意味で受け付ける | 人が打つのは `runo init` だけなので、ここで KUDPC 向けの設定を取り違えないようにする。エージェントや CI からの実行（端末でない、`-y`、引数あり）は従来どおり尋ねない |
| 異常系と同時操作（2026-10-20） | `run.lock` 下で manifest を読み直す、準備の失敗で program を起動しない、adapter を読めなければ purge しない、build cache の key を内容と `build_command` から作る、run の入れ子を禁止、run id を再利用しない（`last_run_id`）、`new --from` で case の変更を警告 | 外部レビューで、二重投入で 1 回目の履歴が消える、準備失敗が completed になる、adapter の故障で保持ファイルが消える、未追跡ファイルの変更で古い binary を使う、削除した id が別の run を指す、を確認した |
| 操作範囲は起動 project（2026-10-21） | AGENTS.md block と skill に「対象は起動した project の run と job id だけ。アカウント全体の squeue / sacct は診断に見るだけ。自分で別 directory に移らず、生の `sbatch` / `scancel` を使わない」を書く。CLI は別 project の path を拒否する | 範囲を言わない「再投入して」で、エージェントが別 project や runops 管理外のジョブまで再投入した。cwd で project を決める既存の model に、path 引数の抜け道（`submit --all /other/runs` など）があった。他 session が修正のために止めた run を見分けられるよう、`cancel --why` を note に残し、`retry` はその理由を示して確認を取る（#112） |
| 置き換えた系列の整理（2026-10-21） | `archive` が DIR（系列）を受け、`--superseded-by` で置き換え先を manifest に記録する。新しい command と tidy の種別は足さない。skill は新系列を作ったら旧系列の要否を確かめ、不要なら archive して現用系列・archive 先・件数を報告する | 修正版を作った後に旧系列が作業領域に残り、毎回ユーザーが整理を頼んでいた。`parent_run` だけでは比較用の派生と置き換えを区別できないので、置き換えは明示操作で記録する。旧 `archive` は 1 件ずつ検査していて、途中の running run で一部だけ移動していた（#113） |
| 生成ハーネスの書き方（2026-10-21） | AGENTS.md の Rules を「作業の進め方」5 項目に絞り、各項目を「何をするか」と短い理由で書く。skill は手順に専念し、AGENTS.md の方針（manifest を手で編集しない等）を繰り返さない | #112・#113 で規則が増え、禁止形（never / do not）が並んでいた。現行の Claude の prompting 指針は、しないことより何をするかを、理由と共に書くことを勧め、強い禁止語は過剰反応を招くとしている |
| 複数 run の mv / archive（2026-10-22） | 1 回の `run.lock` の下で全対象を読み直して検査し、通ってから移す。途中の filesystem error では移し終えた run id を示して止まる | `mv A B C --dest X` は 1 件ずつ検査して移していたので、途中の submitted run で一部だけ移動していた。archive は表示の後で lock を取り直していて、その間に再投入された run で同じことが起き得た |
| FEEDBACK 棚卸し 2.4.0（2026-10-23） | `--job k=v` と `new --from` の `[job]` 継承、created の archive / restore、archived scratch を期限削除しない、展開 skill の references 参照の書き換えと `doctor` のリンク検査、adapter warning への版の併記、生成 AGENTS.md に解析環境の置き場所 | hub の FEEDBACK で、資源変更のための case 編集（3 回）、置換済み draft を archive できず helper で迂回（2 回）、保管目的の archive が期限削除される、skill から reference に辿れない、新版の正規キーが誤記に見える、解析依存の置き場所が project ごとに違う、が記録された。いずれも既存 command の拡張で、command 数は増やさない |
| 使い方ガイド | `docs/guide.md` を追加し、文書を 4 ファイルにする（§13.3） | README の依頼例の表と command 一覧の間を埋める、場面ごとの流れ（case と run の分け方、smoke から本計算、状態の決まり方、整理）の置き場所が無かった |
