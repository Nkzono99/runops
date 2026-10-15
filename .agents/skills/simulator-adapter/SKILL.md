---
name: simulator-adapter
description: "Add or update runops v2 support in a simulator's own Python package (runops.adapters entry point, agent_context_dir packaging, tests), or adjust runops.legacy_adapters. Use when a simulator such as MPIEMSES3D, BEACH, or a new code needs to work with runops."
---

# simulator 側の adapter

runops 本体には simulator 固有の adapter を置かない（SPEC §8.1）。adapter は simulator の
Python package に置き、`runops.adapters` entry point で公開する。

## 手順

1. simulator repo の規約（AGENTS.md、テスト、ログインノードでの実行可否）を読み、作業中の branch を
   壊さないよう `git worktree add -b <branch> <scratch> main` で作業する。
2. `<package>/runops_adapter.py` に `Adapter` を書く。runops は関数内で遅延 import し、
   module の import 時に runops を要求しない。契約は `docs/adapter.md`。
   - `render_inputs` は `runops.adapters.toml_override` で dotted key を適用する
   - `build_command` は run_dir を cwd とした argv、`detect_status` は job 終了後の判定
   - 既存の移植元は `src/runops/legacy_adapters/<name>.py`
3. `pyproject.toml` に entry point を足す:
   `[project.entry-points."runops.adapters"] <name> = "<package>.runops_adapter:Adapter"`
4. skill と reference を wheel に入れ、`agent_context_dir()` で返す。候補は
   `<package>/agent_context`（wheel）→ repo の `plugins/<name>-context`（source checkout）の順。
   - package dir の外にある場合: setuptools の `package-dir` で data-only package に対応付ける
     （BEACH: `"beach.agent_context" = "plugins/beach-context"`）
   - 配布 workflow が package をコピーして build する場合: build 前に stage する script
     （MPIEMSES3D: `tools/stage_agent_context.py`）
5. テスト: `build_command`、`detect_status`、`summarize`、`agent_context_dir` は runops 無しで、
   `render_inputs` は runops があるときだけ（skip）。wheel の中身を確認できるなら
   `agent_context/skills/*/SKILL.md` と `entry_points.txt` の `[runops.adapters]` を見る。
6. E2E: scratch project で `uv venv` → `uv pip install --no-deps <wheel or -e path>` →
   `runo init <name> --no-install` → `runo doctor`（`resolved via entry-point`）→ skill 展開と
   `runo new` の job.sh を確認する。
7. entry point を持つ版が出たら、runops 側の `legacy_adapters/<name>.py` と
   `ops/setup.py` の `KNOWN_PACKAGES` を見直す。
