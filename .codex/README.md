# Codex CLI harness — runops

このディレクトリは runops 開発リポジトリ用の Codex CLI 設定です。
Claude Code 用の `.claude/` と同じ運用思想を共有しますが、Codex では
`AGENTS.md`, `.agents/skills/`, `.codex/config.toml`, `.codex/rules/`
を入口にします。

## 自動読み込みされるもの

- `AGENTS.md`
  — Codex が最初に読むプロジェクト案内。
- `.agents/skills/<name>/SKILL.md`
  — Codex の Agent Skill。`$skill-name` または自動発火で呼ばれる。
- `.codex/config.toml`
  — approval policy / sandbox mode などの project 既定値。
- `.codex/rules/runops.rules`
  — sandbox 外実行に escalation するときの command policy。
- `.codex/rules/*.md`
  — Claude 版 `.claude/rules/*.md` から移した設計・運用リファレンス。

`.codex/config.toml` は **project を trusted に登録しないと読まれません**。
Codex を初めてこのディレクトリで起動したときに trust プロンプトで yes を
選ぶか、手動で `~/.codex/config.toml` に以下を追記してください:

```toml
[projects."<このリポジトリの絶対パス>"]
trust_level = "trusted"
```

## Claude からの移植対応

| Claude Code | Codex | 備考 |
|---|---|---|
| `CLAUDE.md` | `AGENTS.md` | Codex の project doc |
| `.claude/skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` | 呼び出しは `/name` ではなく `$name` |
| `.claude/agents/<name>.md` | `.agents/skills/<name>/SKILL.md` | Codex では専用 agent 定義ではなく skill として読む |
| `.claude/rules/*.md` | `.codex/rules/*.md` / `AGENTS.md` | 設計・運用リファレンス |
| `.claude/settings.json` | `.codex/config.toml` / `.codex/rules/*.rules` | permissions allowlist の完全互換はない |

## 個人用上書き

Codex は各ディレクトリで `AGENTS.override.md` があれば `AGENTS.md` より
優先して読みます。ローカルな一時ルールや作業者固有のメモは
`AGENTS.override.md` に置き、共有したいルールは `AGENTS.md` や
`.agents/skills/` に反映します。

## Command policy

`.codex/rules/*.rules` は sandbox 外実行への escalation に効く command
policy です。runops は `submit`, `delete`, `purge-work`, `rm -rf`,
`git reset --hard`, `git push --force` のような高リスク操作だけをここに
書きます。通常の開発ワークフローや設計方針は `AGENTS.md` と
`.codex/rules/*.md` に置きます。

`runops runs submit --dry-run` は HPC 資源を使わない確認コマンドなので allow
しています。ただし Codex execpolicy は prefix-based なので、`--dry-run` は
`submit` の直後に置いてください:

```bash
runops runs submit --dry-run --all runs/survey -qn gr10451a
```

実投入は必ず会話上でユーザー確認を得てから実行します。
`approval_policy = "never"` / `AskForApproval = Never` の環境では `prompt`
rule が hard block になるため、実投入まで Codex に任せる project では
個人用の `AGENTS.override.md` と user-local execpolicy で明示 opt-in してください。
例:

```starlark
# ~/.codex/rules/runops-submit-approved.rules など user-local に置く
prefix_rule(
    pattern = ["runops", "runs", "submit", "--all"],
    decision = "allow",
    justification = "Only use after explicit chat confirmation in this project.",
)
```

ルールを変更したら、最低限次を確認してください:

```bash
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  runops runs submit --dry-run --all runs/survey
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  runops runs submit --all runs/survey
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  rm -rf runs/R20260419-0001
```

## Hooks

Codex hooks は experimental で、利用には `~/.codex/config.toml` などで
`[features].codex_hooks = true` が必要です。runops 開発リポジトリは初期状態では
`.codex/hooks.json` を生成しません。通常の運用ルールは `AGENTS.md`、定型
ワークフローは `.agents/skills/`、高リスク command の扱いは
`.codex/rules/runops.rules` に置きます。
