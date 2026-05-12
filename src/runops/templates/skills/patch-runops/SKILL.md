---
name: patch-runops
description: Patch runops itself in a separate source checkout, verify the fix, then decide whether it stays local, becomes HarnessOps feedback, draft PR, or ready PR.
---

# runops 本体を別 checkout で patch する

通常の runops project には `tools/runops/` は作られない。runops 本体の bug /
不足機能 / harness 摩擦を修正する必要がある場合は、研究 project とは別の
source checkout を用意して作業する。

この skill は **研究作業を止めないための local hotfix** と、
**upstream に戻すかどうかの判定** を扱う。

## 基本方針

- project 側の `campaign.toml`, `cases/`, `runs/`, `notes/` と runops 本体の変更を混ぜない。
- local patch の正本は別 checkout 内の Git branch / commit とする。
- current project で確認したいときだけ、一時的に `.venv` へ package install する。
- 作業メモや handoff は `notes/YYYY-MM-DD.md` に残す。
- 研究判断が変わる場合だけ `research/agenda.md` も更新する。

## まず分類する

修正前に、何をどこに置くべきかを分類する。

| 分類 | 置き場所 |
|------|----------|
| project 固有の研究判断・実データ・site 秘密 | project 側に残す |
| project 固有 harness override | project 側に残す |
| 汎用 CLI / core / adapter / launcher 修正 | runops source checkout |
| 汎用 scaffold / skill / harness 改善 | runops source checkout の `src/runops/templates/` |
| 一部だけ汎用、または設計が必要 | local patch + `{{ skill_prefix }}feedback-runops` HarnessOps record / issue 下書き |

project 側の生成物をそのまま upstream に入れない:

- `.agents/skills/*`
- `.claude/skills/*`
- `AGENTS.md`
- `CLAUDE.md`
- `research/*`
- `notes/*`
- `campaign.toml`
- `cases/*`
- `runs/*`

## 手順

### 1. source checkout を用意する

既に runops repository が開いているならそれを使う。なければ project の外に clone する。

```bash
git clone https://github.com/Nkzono99/runops.git ../runops-src
cd ../runops-src
git status --short
git branch --show-current
```

未コミット変更や作業 branch がある場合は、既存 patch を壊さない。
続けるか、別 branch に分けるか、ユーザーに確認する。

### 2. branch を切る

```bash
git checkout -b fix/<short-name>
```

### 3. 修正して current project で確認する

runops checkout 内で実装する。project 側で確認が必要な場合だけ、project root から
一時的に install する:

```bash
uv pip install ../runops-src --python .venv/bin/python
```

editable install が必要なのは、同じ project で何度も本体変更を反映しながら
debug する場合だけ:

```bash
uv pip install -e ../runops-src --python .venv/bin/python
```

### 4. 最小テストを実行する

runops checkout 内で対象テストを走らせる:

```bash
uv run pytest <target>
uv run ruff check <target>
uv run ruff format --check <target>
```

### 5. local commit を作る

local patch の正本は Git commit とする。

```bash
git status --short
git add <files>
git commit -m "fix: <summary>"
```

project 側の note に branch / commit / current project での確認結果を残す:

```bash
runo notes append "runops local patch" - <<'EOF'
Context: runops source checkout branch=fix/<short-name>, commit=<sha>.
Patch: <何を直したか>
Current project check: <どの command/run で確認したか>
Upstream disposition: local-only / feedback-issue / draft-pr / ready-pr
EOF
```

## Upstream disposition

local patch 後、必ず次のどれかに分類する。

| 判定 | 意味 | 次の動き |
|------|------|----------|
| `local-only` | project 固有 | project 側に残し、runops 本体には戻さない |
| `feedback-issue` | 一部汎用 / 設計が必要 / draft PR には早い | `{{ skill_prefix }}feedback-runops` で HarnessOps record + issue 下書き |
| `draft-pr` | 実装案も見せたいが設計レビューが必要 | draft PR |
| `ready-pr` | 小さく汎用でテスト済み | 通常 PR |

PR に進む場合は、project 固有の path、研究判断、未サニタイズの実験情報を含めない。
