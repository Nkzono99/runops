# Codex CLI harness — runops

runops 開発リポジトリ用の Codex 設定。Claude Code と同じ正本を共有する。

| 目的 | 正本 | Codex の入口 | Claude Code の入口 |
|---|---|---|---|
| project doc | `AGENTS.md` | `AGENTS.md` | `CLAUDE.md`（`@AGENTS.md`） |
| 規約 | `.claude/rules/*.md` | `AGENTS.md` の表から参照 | 自動で読まれる |
| 定型作業 | `.agents/skills/<name>/SKILL.md` | `$name` / 自動発火 | `.claude/skills/<name>/SKILL.md`（正本を指す入口） |
| 専門 agent | `.agents/skills/spec-reviewer/SKILL.md` | `.codex/agents/spec-reviewer.toml` | `.claude/agents/spec-reviewer.md` |
| 実行 policy | — | `.codex/config.toml`、`.codex/rules/runops.rules` | `.claude/settings.json` |

`tests/test_dev_harness.py` が入口と正本の対応を検査する。skill を足すときは
`.agents/skills/` に書き、`.claude/skills/` には同じ frontmatter の入口だけを置く。

`.codex/config.toml` は project を trusted に登録したときだけ読まれる:

```toml
[projects."<このリポジトリの絶対パス>"]
trust_level = "trusted"
```

この repository では unattended な保守作業を優先し、`sandbox_mode = "danger-full-access"`、
`approval_policy = "never"` を共有設定にしている。高コスト・不可逆な command は
`.codex/rules/runops.rules` で prompt / forbidden にする。
