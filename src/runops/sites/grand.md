# GRAND / HUCC (北海道大学 学際大規模計算機システム)

## システム概要

- **正式名称**: GRAND / Hokkaido University High-Performance Computing and Cloud System
- **ジョブスケジューラ**: PBS Professional
- **リソース指定方式**: `#PBS -l select=...`
- **推奨 Codex plugin**: `GRAND HPC` (`grand-hpc-codex-plugin`)

`runo init` で grand site profile を選ぶと、このファイルが project root の
`SITE.md` としてコピーされ、`GRAND HPC` plugin の導入導線が
`AGENTS.md` / `CLAUDE.md` に残る。

## runops での扱い

grand site profile は PBS Professional 用の `job.sh` 生成、`qsub` 投入、
`qstat` 同期、`qdel` cancel に対応する。

- `site.toml` には `scheduler = "pbs"` が入る
- `launchers.toml` には `type = "mpiexec"` の launcher preset が入る
- `case.toml [job]` の `partition` は PBS queue (`sc`, `ec` など) として扱う
- submit 時の `-qn/--queue-name` は `qsub -q` override になる
- submit 時の `--group <groupname>` は `qsub -W group_list=<groupname>` override になる

GRAND の queue 制限や module 構成は変わることがあるため、実ジョブの設計や
投入前レビューでは引き続き `GRAND HPC` plugin を使う。

## Codex plugin への委譲

GRAND で作業する Agent は、runops の PBS backend とあわせて、最初に
`GRAND HPC` plugin の skill を使う。

主な対応:

- `grand-hpc-task-router`: GRAND/HUCC 作業の入口
- `grand-host-role-routing`: `grand*` login node / `app*` / PBS compute node の判定
- `grand-hpc-safe-workflows`: login node 直実行を避ける安全運用
- `grand-pbs-jobs`: `qsub`, `qstat`, `qdel`, PBS script, queue, `select=...`
- `grand-env-compile`: module / compiler / MPI wrapper / compile workflow
- `grand-storage`: `/home`, `/work`, `show_quota`, Lustre, large output
- `grand-container-workflows`: Singularity / GPU container

## 安全運用

`grand1` - `grand5` は login node として扱う。編集、軽い確認、job script 作成、
`qsub` による投入はよいが、MPI・OpenMP・GPU・container・大規模 I/O を
login node で直接実行しない。

作業開始時の確認:

```bash
hostname -f 2>/dev/null || hostname
pwd
show_quota
module list
qstat -P
```

## PBS リソース指定

GRAND の PBS script は概ね次の形にする。

```bash
#!/bin/bash -l
#PBS -q sc
#PBS -l select=1:nsockets=2:mpiprocs=56
#PBS -l walltime=01:00:00
#PBS -W group_list=<groupname>
#PBS -j oe
#PBS -N mpi_job
set -euo pipefail
cd "${PBS_O_WORKDIR:?}"
```

CPU queue の目安:

| Queue | 用途 |
| --- | --- |
| `ec` | 短時間・小規模 CPU、interactive |
| `sc` | 標準 CPU |
| `lc` | 大規模・長時間 CPU |
| `<groupname>c` | group flat-rate CPU queue |

GPU queue の目安:

| Queue | 用途 |
| --- | --- |
| `eg` | 短時間 GPU / interactive |
| `sg` | 標準 GPU |
| `lg` | multi-node GPU |
| `<groupname>g` | group flat-rate GPU queue |

queue や制限は変わることがあるため、投入前に `qstat -P` と必要なら
`qstat -Qf <queue>` で確認する。

## モジュール

標準的な Intel MPI CPU job では次を基本形にする。

```bash
module purge
module load intel
module load impi
module list
```

手元の `MPIEMSES3D/job-scripts/job-grand.sh` では以下の versioned modules が
使われている。

```bash
module load intel/2025.3.0
module load impi/2021.17
```

version pinning が必要な場合は `show_module -k intel`, `show_module -k impi`,
`module avail` で現行 module を確認してから PBS script に書く。

## MPIEMSES3D PBS script 例

`/home/d30999/work/Github/MPIEMSES3D/job-scripts/job-grand.sh` をもとにした
EMSES 用の最小例。

```bash
#!/bin/bash -l
#PBS -N mpiemses3d_grand
#PBS -q sc
#PBS -l select=1:nsockets=2:mpiprocs=56
#PBS -l walltime=01:00:00
#PBS -W group_list=<groupname>
#PBS -j oe

set -euo pipefail
set -x

module purge
module load intel/2025.3.0
module load impi/2021.17
module list

cd "${PBS_O_WORKDIR:-$PWD}"

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export EMSES_DEBUG="${EMSES_DEBUG:-no}"

INPUT="${INPUT:-plasma.toml}"
JOB_ID="${PBS_JOBID:-manual}"
JOB_TAG="${JOB_ID%%.*}"
OUTPUT_DIR="${OUTPUT_DIR:-output_${JOB_TAG}}"

if [[ -z "${MPI_PROCS:-}" ]]; then
  if [[ -n "${PBS_NODEFILE:-}" && -f "${PBS_NODEFILE}" ]]; then
    MPI_PROCS="$(wc -l < "${PBS_NODEFILE}")"
  else
    MPI_PROCS=56
  fi
fi

mkdir -p "${OUTPUT_DIR}"

date
mpiexec -n "${MPI_PROCS}" ./mpiemses3D -o "${OUTPUT_DIR}" "${INPUT}"
date
```

## Storage

- 大きな出力は `/home` に置かず、`show_quota` で確認した quota-backed な
  `/work` または `/lustre*/work` 配下を使う
- job script 内では `PBS_O_WORKDIR` を起点にし、必要なら明示的な `GRAND_WORK_ROOT`
  を環境変数で渡す
- 大きな単一ファイル I/O では `lfs setstripe` を検討する
- file count 制限でも `No space left on device` が出ることがある

## 投入・監視

```bash
qsub job.sh
qstat
qstat -f <jobid>
qstat -x
qdel <jobid>
```

連続 polling loop は避け、必要なタイミングで一回ずつ確認する。
