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
  — sandbox mode、approval mode、web search、project doc budget などの
  repo-local 既定値。
- `.codex/rules/runops.rules`
  — sandbox 外実行に escalation するときの command policy。
- `.codex/rules/*.md`
  — Claude 版 `.claude/rules/*.md` から移した設計・運用リファレンス。
- `.codex/automation-prompts/*.md`
  — Codex Automation 登録から参照する長い handoff prompt。
  Automation 側には短い参照文だけを置き、実行手順は Git 管理する。

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

## 設定の責務分離

`.codex/config.toml` は、runops 開発リポジトリで共有する repo-local default
を置きます。この repository では Issue triage automation が `git pull`,
GitHub issue 確認、web search、修正、test、commit、push まで unattended に
実行できることを優先し、`sandbox_mode = "danger-full-access"`,
`approval_policy = "never"`, `web_search = "live"` を共有設定にします。

- `.codex/config.toml`
  — repo-local default。project trust 後に読み、local automation の既定許可
  モードもここで固定する。
- `.codex/rules/*.rules`
  — `submit`, `delete`, `rm -rf` など高コストまたは不可逆な command の policy。
- Codex runtime / `~/.codex/config.toml`
  — machine 全体の model、plugins、UI、個人 preference など、runops 以外にも
  影響する設定。

Codex の web 検索は `web_search = "live"` で有効化します。shell command の
network は sandbox mode / permissions profile 側の領域で、runops の
automation では `danger-full-access` によって `git`, GitHub, PyPI,
`runo knowledge source sync` などの通常の保守作業を許可します。

## 個人用上書き

Codex は各ディレクトリで `AGENTS.override.md` があれば `AGENTS.md` より
優先して読みます。ローカルな一時ルールや作業者固有のメモは
`AGENTS.override.md` に置き、共有したいルールは `AGENTS.md` や
`.agents/skills/` に反映します。

## Command policy

`.codex/rules/*.rules` は sandbox 外実行への escalation に効く command
policy です。runops は `submit`, `delete`, `purge-work`, `rm -rf`,
`git reset --hard`, `git push --force` のような高コストまたは不可逆な操作だけを
ここに書きます。通常の開発ワークフローや設計方針は `AGENTS.md` と
`.codex/rules/*.md` に置きます。

`runo runs submit --dry-run` は HPC 資源を使わない確認コマンドです:

```bash
runo runs submit --dry-run --all runs/survey -qn gr10451a
```

実投入は必ず会話上でユーザー確認を得てから実行します。`submit` は破壊的操作
ではありませんが、HPC 資源・queue・quota に影響します。default の project
rule は `runo runs submit` / `runops runs submit` を permission layer では
`allow` します。ここで `--all` だけを `prompt` にすると、`approval_policy =
"never"` 環境で bulk submit が hard block され、Agent が個別 submit に分解して
迂回する悪い動きを誘発するためです。

Agent 側の行動ルールは AGENTS.md / skills 側に置きます:

- まず `runo runs submit --dry-run ...` で対象 run と skip を確認する
- 実行前に command、対象 run、queue、QOS、資源量を会話上で提示する
- ユーザーの明示確認後に submit する
- policy や環境で bulk submit が止まった場合、個別 submit に分解して迂回しない

ルールを変更したら、最低限次を確認してください:

```bash
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  runo runs submit --dry-run --all runs/survey
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  runo runs submit --all runs/survey --dry-run
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  runo runs submit --all runs/survey
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  runo runs submit --all runs/survey --yes
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  runo runs submit R20260419-0001
codex execpolicy check --pretty --rules .codex/rules/runops.rules -- \
  rm -rf runs/R20260419-0001
```

submit 系は `allow`、`rm -rf` は `forbidden` になっていることを確認してください。

## Automation prompts

Local Automation の登録本文は短く保ち、詳細な実行手順は
`.codex/automation-prompts/` に置きます。たとえば
`runops-issue-triage-and-run` は
`.codex/automation-prompts/runops-issue-triage-and-run.md` を読むだけにします。
これにより prompt の改善は通常の Git diff / review / commit で管理できます。
この prompt には HarnessOps scaffold の取り込みも含め、`hops update-harness
--agent-bridge --codex` を定期的に通します。

## Hooks

Codex hooks は experimental で、利用には `~/.codex/config.toml` などで
`[features].codex_hooks = true` が必要です。runops 開発リポジトリは初期状態では
`.codex/hooks.json` を生成しません。通常の運用ルールは `AGENTS.md`、定型
ワークフローは `.agents/skills/`、高コストまたは不可逆な command の扱いは
`.codex/rules/runops.rules` に置きます。
