---
name: emses
description: "Use when working with MPIEMSES3D through runops. Keep this as a thin runops bridge; delegate simulator-specific parameter design, input review, run diagnosis, output analysis, and visualization to MPIEMSES3D Context and emout Context plugins when available."
---

# EMSES runops bridge

この skill は runops 開発リポジトリ側の薄い橋渡しである。MPIEMSES3D 固有の
長文知識、物理・数値判断、`plasma.inp` review、run diagnosis、HDF5/emout
解析、可視化 workflow は外部 Codex plugin `MPIEMSES3D Context`
(`mpiemses3d-context`) と `emout Context` (`emout-context`) に委譲する。
runops 側では run directory、case/survey 展開、manifest、adapter contract、
launcher/job.sh、lint/test/docs の整合性だけを扱う。

## 最初に確認すること

1. 対象 project で `runo plugins --check` または `runo plugins --json` を確認し、
   `mpiemses3d-context` / `emout-context` 推薦と `delegated_capabilities` を見る。
2. 現在の Codex session で external plugin / skill が利用可能なら、
   `input-review`, `parameter-design`, `run-diagnose`, `output-analysis`,
   `visualization-script` はそちらを使う。
3. plugin が利用できない場合だけ、この skill の最小情報と現在の project files
   (`case.toml`, `plasma.inp`, `manifest.toml`, stdout/HDF5 output) を根拠にする。

## runops 側で担当すること

- `src/runops/adapters/contrib/emses/adapter.py` の adapter contract、runtime
  resolution、input rendering、required outputs、summary parsing を保つ。
- launcher / jobgen では Python を MPI rank wrapper にせず、job.sh から
  `srun` / `mpirun` / `mpiexec` を直接起動する境界を守る。
- `runo create`, `runo submit`, `runo status`, `runo summarize`, `runo collect`
  から見た runops workflow を壊さない。
- EMSES project では `runo plugins` が `MPIEMSES3D Context` と `emout Context`
  の委譲 role を表示することを確認する。
- KUDPC 上で実行やテストを行う場合は KUDPC plugin の routing に従い、login node
  で solver、pytest、可視化、重い解析を直接実行しない。

## 最小 fallback

- 代表入力は `plasma.inp` と optional `plasma.preinp`。
- 代表 output は stdout/stderr log と `*_0000.h5` 系 HDF5 files。
- runops の状態追跡は `manifest.toml` と adapter output detection を正本にする。
- 詳細な namelist 意味、安定性判断、emout API、図化手順は plugin または upstream
  docs を根拠にし、この repository の古い記憶で補完しない。

## 変更時の検証

- Adapter 変更: `tests/test_adapters/test_emses.py`,
  `tests/test_adapters/test_contract.py`
- launcher/job.sh 変更: `tests/test_launchers/`, `tests/test_slurm/test_jobgen.py`
- plugin 推薦変更: `tests/test_core/test_plugins.py`,
  `tests/test_cli/test_plugins.py`, `tests/test_core/test_context.py`,
  `tests/test_mcp/test_tools.py`
- harness 表示変更: `tests/test_harness/test_codex.py`,
  `tests/test_cli/test_init.py`, `tests/test_cli/test_update_harness.py`
