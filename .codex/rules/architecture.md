# アーキテクチャ原則

## レイヤ構造

```
cli/          ← 薄い入口。typer + 引数パース + echo のみ
core/         ← ドメインロジック。CLI / scheduler CLI に依存しない
adapters/     ← Simulator 固有処理の抽象化
launchers/    ← MPI 起動方式の抽象化
slurm/        ← Slurm CLI (sbatch, squeue, sacct) のラッパー
pbs/          ← PBS CLI (qsub, qstat, qdel) のラッパー
harness/      ← Agent ハーネス (CLAUDE.md / AGENTS.md, settings/config, builder)
jobgen/       ← job.sh テンプレート生成
templates/    ← Jinja2 + 静的テンプレート (init が scaffold に使う)
```

## 守るべき境界

- **CLI は薄い層**: `cli/*.py` は引数解析と出力整形だけ。ロジックは `core/` に置く
- **core は外部に依存しない**: `core/` が `cli/`, `slurm/`, `adapters/` を import してはいけない
- **Adapter パターン**: simulator 固有の振る舞いは `adapters/base.SimulatorAdapter` を継承して閉じ込める。core が adapter 実装を直接 import しない
- **Launcher パターン**: MPI 起動は `launchers/base.Launcher` を継承。job.sh で直接 srun/mpirun を呼ぶ
- **MPI に介入しない**: Python が MPI rank 内で走るラッパーにならない

## manifest.toml が正本

run の状態・由来・provenance はすべて `manifest.toml` に記録される。
手動編集は禁止。`core/manifest.py` 経由のみ。

## research/ は研究判断の隔離層

生成 project 側の `research/agenda.md` は mutable な現在判断の台帳。
`notes/YYYY-MM-DD.md` / `notes/history/YYYY/YYYY-MM-DD.md` の時系列ログ、
`.runops/` の機械状態、`.agents/skills/` の手順とは混ぜない。
本文は日本語で書き、コード・コマンド・ファイルパス・run_id は実際の表記のまま残す。

## ハーネス二重構造

runops は **2 種類のハーネス** を持つ:

1. **このリポジトリ自身の `.claude/`, `.codex/`, `.agents/skills/`** — runops 開発者向け
2. **`src/runops/templates/` → `runo init` が生成するプロジェクト側ハーネス** — runops ユーザーのプロジェクト向け

`harness/builder.py` がプロジェクト側のハーネス生成を担う。
`update-harness` が既存プロジェクトへの反映を担う。

変更時は「どちらのハーネスか」を意識する。
