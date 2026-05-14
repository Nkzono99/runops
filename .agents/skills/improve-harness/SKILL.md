---
name: improve-harness
description: "Trigger when the user asks to improve, audit, port, or update the AI agent harness configuration for runops. Covers AGENTS.md, CLAUDE.md, .claude/, .codex/, .agents/skills/, and scaffolded project-side harness templates in src/runops/templates/."
---

# Harness 改善スキル

runops には **2 つのハーネス** がある。どちらを改善するか確認すること:

| ハーネス | 場所 | 対象者 |
|---|---|---|
| **開発ハーネス** | `.claude/`, `.codex/`, `.agents/skills/` (このリポジトリ直下) | runops 開発者 |
| **プロジェクトハーネス** | `src/runops/templates/` → `runops init` が生成 | runops を使うプロジェクトのエージェント |

## 改善の進め方

### 1. 現状の監査

```bash
# 開発ハーネスの構成確認
ls -R .claude/
ls -R .codex/
ls -R .agents/skills/

# プロジェクトハーネスのテンプレート
ls src/runops/templates/harness/
ls src/runops/templates/skills/
```

### 2. 改善パターン

**ルール / project doc (`AGENTS.md`, `.codex/rules/`)** — 開発中にエージェントが守るべき制約
- 品質ゲート (lint, test, type check)
- アーキテクチャ境界
- よくあるミス (Gotchas)
- ワークフロー規約
- 高コスト / 不可逆 command の policy
- `AGENTS.md` は入口に限定し、150 行程度を超えそうなら `.codex/rules/` か skill に分離

**スキル (`.agents/skills/<name>/SKILL.md`)** — 繰り返す定型作業
- description はトリガー条件を書く (「いつ発火すべきか」)
- ゴールと制約を書き、手順は詳細にしすぎない
- scripts/ や examples/ のサブディレクトリで progressive disclosure

**Claude agent 由来の専門スキル (`.agents/skills/<name>/SKILL.md`)** — Codex では agent 定義ではなく skill として移植する
- 実装系 (implement-core, implement-cli, etc.)
- シミュレータ系 (emses, beach)
- レビュー系 (spec-reviewer, test-writer)

**設定 / policy (`.codex/config.toml`, `.codex/rules/*.rules`)** — 実行環境と高コスト / 不可逆操作
- `approval_policy`, `sandbox_mode` — Codex の既定実行モード
- `prefix_rule(...)` — `submit`, `delete`, `rm -rf`, `git reset --hard` などの扱い

### 3. プロジェクトハーネスの変更

プロジェクト側テンプレートを変更した場合:
- `src/runops/templates/` のファイルを編集
- `harness/builder.py` の `build_harness_bundle()` に新ファイルを追加
- `tests/test_cli/test_init.py` にテストを追加
- `tests/test_cli/test_update_harness.py` にテストを追加
- 既存プロジェクトには `runops update-harness` で反映される

### 4. 検証

```bash
# Lint/type/test
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/test_cli/test_init.py tests/test_cli/test_update_harness.py -x -q

# init が正しく生成するか確認
cd /tmp && mkdir test-harness && cd test-harness
uv run --directory <repo> runops init -y
ls -la .codex/rules/ .agents/skills/
```

## Gotchas

- ルールファイルを追加しただけでは `build_harness_bundle` に含まれない。
  builder.py にエントリを足す必要がある (プロジェクトハーネスの場合)
- 開発ハーネス (`.claude/`, `.codex/`, `.agents/skills/`) は builder を経由しない。直接ファイルを置く
- `.claude/settings.json` の `allow` / `deny` と `.codex/rules/*.rules` は完全互換ではない。Codex 側は高コスト / 不可逆操作の policy に絞る
- AGENTS.md は長くなりすぎないようにする。長いコマンド表は `.codex/rules/commands.md`、定型手順は `.agents/skills/`、高コスト / 不可逆 command policy は `.codex/rules/` に分離
- `project_doc_max_bytes` を上げて解決しない。まず AGENTS.md を短くし、詳細は progressive disclosure にする
