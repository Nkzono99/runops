# runops リファレンス

`runops.toml`、`case.toml`、`manifest.toml` の field と、全 command の動作です。
設計の背景は [SPEC.md](../SPEC.md) にあります。

## runops.toml

project root にあり、`runo` はここを上方向に探して project を特定します。
command はこの project の `runs/` 配下だけを扱い、別 project の run directory や
directory を path で渡すとエラーになります。run id は project ごとなので、同じ id が
別 project にあっても cwd の project の run を指します。

```toml
schema = 2

[project]
name = "lunar-sheath"

[site]
name = "kudpc"
resource_style = "rsc"            # "standard" | "rsc"
modules = ["intel/2023.2", "intelmpi/2023.2"]
stdout = "stdout.%J.log"          # 省略時は work/%j.out
stderr = "stderr.%J.log"          # 省略時は work/%j.err
extra_sbatch = []
setup_commands = []

[site.env]
OMP_PROC_BIND = "spread"

[simulators.emses]
adapter = "emses"                 # adapter 名（entry point / adapters/<name>.py / generic）
package = "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git"
executable = "mpiemses3D"
resolver_mode = "package"         # package | local_executable | local_source
modules = ["hdf5/1.12.2_intel-2023.2-impi"]

[simulators.beach_patched]        # 同じ adapter を複数の build で使い分けてよい
adapter = "beach"
resolver_mode = "local_source"
source_repo = "../BEACH"
build_command = "./build.sh"
executable = "build/bin/beach"    # build directory からの相対 path

[launchers.srun]
kind = "srun"                     # srun | mpirun | mpiexec | none
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

| resolver_mode | executable の解決 |
|---|---|
| `package` | `.venv/bin/<executable>`、無ければ PATH |
| `local_executable` | 絶対 path、project 相対 path、PATH の順 |
| `local_source` | `source_repo` の HEAD を `.runops/build/<sim>-<commit>-<hash>/` にコピーし `build_command` を実行。`<hash>` は `build_command` と、dirty なら未追跡を含む全ファイルの内容から作る（dirty なら `-dirty` も付く） |

module は site、launcher、simulator、case の順に結合されます。`generic` adapter では
`command`（`{executable}` を置換）と `success_marker`（`work/` 内の完了 marker）も使えます。
未知の key は warning を出して無視します。

## case.toml

`cases/<name>/case.toml` と、同じ directory の base 入力ファイルで case になります。
`cases/<name>/input/` の中身も run の `input/` にコピーされます。

```toml
[case]
name = "flat"
simulator = "emses"
launcher = "srun"                 # 省略時は defaults.launcher
description = "平板シース"
tags = ["sheath"]

[job]
partition = "gr20001a"
walltime = "120:00:00"            # [D-]H:MM:SS
nodes = 1                         # standard: nodes / ntasks / cpus_per_task
ntasks = 800
# processes = 1                   # rsc: --rsc p=processes:t=threads:c=cores
# threads = 112
# cores = 112
# qos, memory, gpus, job_name, extra_sbatch, pre_commands, post_commands, modules

[params]
"tmgrid.nx" = 4000                # dotted key で base 入力を上書き

[naming.aliases]
"plasma.phiz" = "angle"           # 自動 label の短縮名
```

dotted key は `a.b`、配列要素は `species.0.wp` または `species[0].wp` です。
値の違いは case を増やさず、`runo new --set` や `runo sweep` で run として表します。

## manifest.toml

runops だけが書きます。手で編集しないでください。主な field は次の通りです。

| section | field |
|---|---|
| `[run]` | `id`、`label`、`status`、`created_at`、`why`、`scratch`、`expires_at`、`pinned`、`tags`、`status_before_archive`、`superseded_by`（置き換え先の run id） |
| `[path]` | `run_dir`（project 相対）、`archived_from`、`archived_at` |
| `[origin]` | `case`、`sweep`、`parent_run`、`created_by`、`case_input_hash` |
| `[simulator]` | `name`、`adapter`、`adapter_source`、`adapter_version`、`executable`、`resolver_mode`、`package_version`、`exe_hash`、`git_commit`、`git_dirty`、`build_dir` |
| `[job]` | case の `[job]` に加え `job_id`、`attempt`、`submitted_at`、`finished_at`、`last_slurm_state`、`exit_code`、`[[job.attempts]]`（attempt ごとの `job_id`、`started_at`、`exit_code`、`exe_hash`、`elapsed`、`cancel --why` の `cancel_reason`） |
| `[params]` | case の params に `--set` を適用した最終値 |
| `[variation]` | `changed_keys` |
| `[identity]` | `input_hash` |
| `[storage]` | `work_purged_at` |
| `[[notes]]` | `at`、`by`、`text` |

状態は `created → submitted → running → completed | failed | cancelled` と進み、
終了した run は `archived` にできます。`sync` は Slurm が COMPLETED でも adapter が
失敗と判定すれば `failed` にします。job.sh は終了時に `submit/exit.<job_id>`（exit code、
開始・終了時刻、`stage`）を書くので、Slurm の会計から消えた job もこの file で completed / failed が
決まります。`module load`、`cd`、`setup_commands`、`pre_commands` などの準備が失敗すると、job.sh は
program を起動せずに終わり、`stage = "setup"` と exit code を記録します。
`sync` と `tidy` は対象 run の job id をまとめて 1 回の `squeue` と `sacct` で
問い合わせます。runops が知らない Slurm 状態の job は状態を変えず、
`last_slurm_state` にその状態だけを記録します。

`submit` は executable を hash し直して attempt に記録し、作成時と違えば警告します。
`new` と `sweep --apply` は同じ入力（`input_hash`）の run が既にあれば警告します。
`new --from RUN` は、元の run を作った後に case の入力ファイルが変わっていれば警告します
（入力は今の case から作るため）。どれも作成や投入は拒否しません。

`submit`、`cancel`、`retry`、`sync` は lock の中で manifest を読み直してから更新します。
同じ run を 2 回指定しても、複数のエージェントが同時に投入しても sbatch は 1 回です。
run id は削除後も再利用しません。`--dest` に既存 run の中は指定できません。

## command

`list --json` と `status --json` は、walltime の根拠として `walltime`、最新 attempt の `elapsed`、
`walltime_used`（elapsed / walltime）、`slurm_state` も返します。表では `TIMEOUT` などを
`failed (TIMEOUT)` と示します。

全 command は `--help` で option を確認できます。`RUN` には run id、run directory、
または directory 名の一意な部分文字列を渡せます。

| command | 動作 |
|---|---|
| `runo init [SIM...] [--site kudpc\|standard] [--no-install] [-y]` | project を作る。`SIM` は `emses` や `name=package-spec`。端末から引数なしで実行すると site と simulator を尋ねる。`--site` の既定はホスト名から推定（KUDPC のログインノードなら `kudpc`、`camphor` も同義） |
| `runo doctor [--json]` | 設定、adapter の解決経路、executable、sbatch、skill の鮮度を点検 |
| `runo update [--skills-only] [-y]` | simulator package を更新し skill と AGENTS.md の管理 block を再生成 |
| `runo build SIM [--force]` | `local_source` の simulator を build |
| `runo context [--json]` | agent 向けの現在地 |
| `runo case new NAME [-s SIM] [--from CASE]` / `runo case list` | case の作成と一覧 |
| `runo new CASE [--why] [--label] [--set k=v]... [--tag] [--scratch] [--dest DIR] [--submit] [--json]` | run を 1 つ作る |
| `runo new --from RUN [--set k=v]... [--continue]` | 既存 run の params から派生。`--continue` は adapter の restart 対応が必要 |
| `runo sweep CASE --set k=v1,v2 ... [--names k=n1,n2...] [--label] [--dest DIR] [--limit N] [--apply] [--submit] [--json]` | 直積の候補表示。`--apply` で作成。`--names` は各値の短い label、`--dest` は sweep directory の親 |
| `runo submit RUN... [-p P] [--qos Q] [--afterok JOB]` / `runo submit --all [DIR] [-y]` | job.sh を生成して sbatch |
| `runo cancel RUN... [--why TEXT] [-y]` / `runo retry RUN [--submit] [-y]` | scancel（`--why` は note に残る）/ failed・cancelled を created に戻す（理由付きで cancel された run は確認を取る） |
| `runo status [RUN...]` / `runo sync [RUN...]` / `runo log RUN [--err] [-n N] [-f]` | 状態表示 / Slurm から更新 / log 表示 |
| `runo list [PATH] [--all] [--since 30d] [--case] [--sweep] [--status] [--tag] [--scratch] [--archived] [--json]` | run 一覧 |
| `runo note RUN [TEXT]` / `runo pin RUN [--off] [--reason]` | ノート追記・表示 / pin |
| `runo summarize RUN... [--force]` | adapter の要約を `analysis/summary.json` に書く |
| `runo mv RUN... [--dest DIR] [--label L] [--why TEXT]` | `runs/` 配下で改名・移動。id、入力、sweep、ノートは保つ。submitted / running と archived は不可。全対象を検査してから移し、1 件でも不可なら何も動かさない |
| `runo archive RUN\|DIR... [--superseded-by RUN\|DIR --why TEXT]` / `runo archive --older-than 90d` / `runo restore RUN` | `runs/_archive/` へ移動 / 戻す。移動前に全対象を検査し、指定した RUN が終了していなければ何も動かさない。DIR は配下の run（系列）で、created / submitted / running と pinned を除いて表示する。`--superseded-by` は置き換え先（その run から `--from` で派生した run、無ければ指定した全 run）を `superseded_by` に記録し、`--why` をノートに残す |
| `runo delete RUN... [-y]` | created・failed・cancelled・scratch の run を削除 |
| `runo tidy [--apply] [--only KIND] [--older-than AGE] [--purge-work RUN...]` | 整理候補の表示と実行 |
| `runo migrate-v1 [--dry-run] [--apply-delete-test-runs] [-y]` | v1 project の変換 |

`list` は既定で active、created、直近 `list_since_days` 日、pinned の run を表示し、
scratch と archived は表示しません。

`tidy` の候補は次の 5 種類です。

| kind | 条件 | 動作 |
|---|---|---|
| `expired-scratch` | 期限切れの scratch run | delete |
| `stale-failed` | `tidy_failed_days`（既定 30）日より古い failed / cancelled で、why も note も無い | delete |
| `old-completed` | `tidy_archive_days`（既定 90）日より古い completed | archive |
| `orphan-job` | Slurm が知らない submitted / running | sync |
| `unused-build` | 非 archived run が参照しない `.runops/build/*` | delete |

日数は `runops.toml` の `[defaults]` で変えられます。`--older-than 14d` のように指定すると、
その回だけ両方の日数をその値で置き換えます。pinned の run は `tidy` と `delete` の対象になりません。
`--purge-work` は adapter を読み込めないと何も消さずにエラーにします。

exit code は 0 が成功、1 が実行時エラー（sbatch 失敗など）、2 が使い方や設定のエラーです。
