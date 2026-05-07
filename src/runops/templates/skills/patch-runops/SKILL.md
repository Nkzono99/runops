---
name: patch-runops
description: Locally patch tools/runops for the current project, use the editable install immediately, then decide whether the change stays local, becomes feedback-runops issue, draft PR, or ready PR.
---

# tools/runops を local patch する

`tools/runops/` は editable install されているため、current project で困った
runops 本体の bug / 不足機能 / harness 摩擦を、その場で修正して即利用できる。

この skill は **研究作業を止めないための local hotfix** と、
**upstream に戻すかどうかの判定** を扱う。

## 基本方針

- `update-runops` は local changes を壊さない。
- local patch の正本は `tools/runops` 内の Git branch / commit とする。
- 別枠の mutable patch 履歴はデフォルトでは作らない。stale になりやすい。
- 作業メモや handoff は `notes/YYYY-MM-DD.md` に残す。
- 研究判断が変わる場合だけ `research/agenda.md` も更新する。
- 長期化して複数 patch が並ぶ場合だけ、`notes/reports/runops-local-patches.md`
  のような project-local index を作ってよい。

## まず分類する

修正前に、何をどこに置くべきかを分類する。

| 分類 | 置き場所 |
|------|----------|
| project 固有の研究判断・実データ・site 秘密 | project 側に残す |
| project 固有 harness override | project 側に残す |
| 汎用 CLI / core / adapter / launcher 修正 | `tools/runops` で patch |
| 汎用 scaffold / skill / harness 改善 | `tools/runops/src/runops/templates/` へ戻す |
| 一部だけ汎用、または設計が必要 | local patch + `feedback-runops` issue |

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

汎用化する場合は source template 側へ移す:

- project `.agents/skills/foo/SKILL.md` → `tools/runops/src/runops/templates/skills/foo/SKILL.md`
- project `AGENTS.md` / `CLAUDE.md` 改善 → `tools/runops/src/runops/templates/harness/shared/partials/`
- project `research/` scaffold 改善 → `tools/runops/src/runops/templates/scaffold/research/`

## 手順

### 1. tools/runops の状態確認

```bash
cd tools/runops
git status --short
git branch --show-current
git log --oneline -5
```

未コミット変更や作業 branch がある場合は、既存 patch を壊さない。
続けるか、別 branch に分けるか、ユーザーに確認する。

### 2. branch を切る

```bash
git checkout -b fix/<short-name>
```

### 3. 修正して current project で即確認する

通常は editable install のため、Python code / template 変更はそのまま効く。
依存関係、entry point、package metadata を変えた場合だけ project root で
install を更新する:

```bash
uv pip install -e tools/runops --python .venv/bin/python
```

### 4. 最小テストを実行する

`tools/runops` 内で対象テストを走らせる:

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
cd ../..
runo notes append "runops local patch" - <<'EOF'
Context: tools/runops branch=fix/<short-name>, commit=<sha>.
Patch: <何を直したか>
Current project check: <どの command/run で確認したか>
Upstream disposition: local-only / feedback-issue / draft-pr / ready-pr
EOF
```

## Upstream disposition

local patch 後、必ず次のどれかに分類する。

### local-only

project 固有。upstream しない。

例:

- 特定 campaign だけの temporary workaround
- private path / cluster 秘密に依存する修正
- 研究判断そのもの

### feedback-issue

汎用価値はありそうだが、設計がまだ粗い / 影響範囲が大きい /
一部だけ汎用 / draft PR には早い。

この場合は `{{ skill_prefix }}feedback-runops` で issue 化する。issue には local branch / commit、
current project で効いたこと、upstream にしたい部分、project 固有として
除外すべき部分を書く。

### draft-pr

実装案も見せたいが、設計レビューが必要。

```bash
git push origin fix/<short-name>
gh pr create --repo Nkzono99/runops --draft
```

### ready-pr

小さく汎用で、テストもある。

```bash
git push origin fix/<short-name>
gh pr create --repo Nkzono99/runops
```

## 報告フォーマット

最後に必ずこの形で報告する:

```markdown
## Local patch result

- Branch:
- Commit:
- Current project check:
- Tests:
- Upstream disposition: local-only / feedback-issue / draft-pr / ready-pr
- Project-specific parts:
- Upstreamable parts:
- Private info excluded:
```

## 注意

- `git reset --hard` で local patch を消さない。
- `update-runops` で pull が block されたら、この skill で patch を整理する。
- PR / issue はユーザー確認なしに作らない。
- current project の作業を止めない。まず local patch で進め、upstream は
  side channel として扱う。
