# Camphor3 (京都大学 学術情報メディアセンター)

公式マニュアル: <https://web.kudpc.kyoto-u.ac.jp/manual/ja>

## システム概要

- **正式名称**: camphor3 (Fujitsu PRIMEHPC FX1000 / CX2550)
- **ジョブスケジューラ**: Slurm (Fujitsu 拡張)
- **リソース指定方式**: `--rsc` (Fujitsu 独自拡張)
- **推奨 Codex plugin**: `KUDPC HPC` (`kudpc-hpc-codex-plugin`)

`runo init` で camphor site profile を選ぶと、KUDPC の host role routing、
ログインノード/アプリケーションサーバ/計算ノードの使い分け、`tssrun` /
`sbatch` / `srun`、`--rsc`、Modules、コンパイル確認を扱う `KUDPC HPC`
plugin の導入導線が `AGENTS.md` / `CLAUDE.md` に残る。private repo のため、
利用環境で GitHub 認証またはローカル checkout marketplace が必要になる。

## リソース指定 (--rsc)

camphor では標準の `--nodes`/`--ntasks` ではなく、`--rsc` ディレクティブを使用する:

```bash
#SBATCH --rsc p=<processes>:t=<threads>:c=<cores>
```

| パラメータ | 意味 | 例 |
|-----------|------|-----|
| `p` | MPI プロセス数 | `p=800` |
| `t` | プロセスあたりスレッド数 | `t=1` (pure MPI), `t=4` (hybrid) |
| `c` | プロセスあたりコア数 (≥ t) | `c=1` (pure MPI), `c=4` (hybrid) |
| `m` | プロセスあたりメモリ (オプション) | `m=8G` |
| `g` | GPU 数 (オプション) | `g=1` |

### 典型的なパターン

**Pure MPI (800 プロセス)**:
```toml
[job]
partition = "gr20001a"
processes = 800
threads = 1
cores = 1
walltime = "120:00:00"
```

**Hybrid MPI+OpenMP (200 プロセス × 4 スレッド)**:
```toml
[job]
partition = "gr20001a"
processes = 200
threads = 4
cores = 4
walltime = "120:00:00"
```

## パーティション

利用可能なパーティションはグループ割当により異なる。
`runops doctor` で自動検出される (`environment.toml` に保存)。

一般的な命名規則: `gr<グループID><サフィックス>`

## モジュール

camphor のサイトプロファイルで自動ロードされるモジュール:

| モジュール | 用途 |
|-----------|------|
| `intel/2023.2` | Intel コンパイラ |
| `intelmpi/2023.2` | Intel MPI |

シミュレータ別の追加モジュール:

| シミュレータ | モジュール |
|-------------|-----------|
| EMSES | `hdf5/1.12.2_intel-2023.2-impi`, `fftw/3.3.10_intel-2022.3-impi` |
| BEACH | (追加なし) |

## ジョブスクリプト例

`runops runs submit` が自動生成する `job.sh` の典型例:

```bash
#!/bin/bash
#SBATCH -p gr20001a
#SBATCH --rsc p=800:t=1:c=1
#SBATCH -t 120:00:00
#SBATCH -o stdout.%J.log
#SBATCH -e stderr.%J.log
#SBATCH -J R0001

module load intel/2023.2 intelmpi/2023.2 hdf5/1.12.2_intel-2023.2-impi fftw/3.3.10_intel-2022.3-impi

cd /path/to/run
date
srun ./mpiemses3D input/plasma.toml -o work/latest
date
```

## QOS (Quality of Service)

camphor では **partition 名と QOS 名が一致** しており、partition を指定すれば
対応する QOS が暗黙的に適用される。

- `sbatch --qos=...` を **直接指定すると `forbidden option` エラー** になる
  (Fujitsu Slurm 拡張による制限)
- そのため `case.toml` の `qos` フィールドや `runops runs submit --qos` は
  **camphor では使用しない**
- partition を `-qn` で override すれば、QOS もそれに連動して変わる

```bash
# OK: partition 指定で QOS も暗黙的に決まる
runops runs submit -qn gr10451a

# NG: camphor では forbidden option エラー
runops runs submit --qos gr10451a
```

## 注意事項

- `srun` 使用時、`--ntasks` は省略可能 (Slurm が `--rsc` の `p` 値を `SLURM_NTASKS` に自動設定)
- ジョブ名 (`-J`) には run_id が自動設定される
- stdout/stderr は `stdout.<JOB_ID>.log` / `stderr.<JOB_ID>.log` 形式
