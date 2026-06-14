---
name: setup-plugins
description: Install, activate, or verify Codex plugins recommended by a generated runops project. Use after runo init/setup/update-harness, or when the user asks to set up simulator/site plugins, plugin activation, or plugin-provided Codex hooks for the project.
---

# 推奨 Codex plugins をセットアップする

runops project が持つ推奨 plugin metadata を読み、必要な Codex plugin の
install / enable / activation / plugin-provided hook 導線を整える。

runops 本体は user-local な Codex plugin 状態を管理しない。この skill は Agent が
その作業を代行・補助するための入口であり、project 側 metadata と plugin 側手順を
正本として扱う。

## 安全原則

- まず `runo plugins --check` と `runo plugins --json` を読む。
- `install_hint` / `activation_hint` / plugin 側 README なしに、独自の install 手順を
  作らない。
- `~/.codex/**`, `$CODEX_HOME/**`, plugin cache、user-local marketplace、hook 設定など
  project 外の状態を変更する前に、変更対象、理由、実行コマンド、戻し方を短く示す。
- token、private repo URL、認証情報をログや note に残さない。
- `curl | sh`、`bash <(curl ...)`、`git reset --hard`、`rm -rf` などを install 手順として
  実行しない。plugin 側が要求していても、ユーザー確認と代替案の提示を挟む。
- Codex hooks は experimental。plugin が hook を提供している場合だけ、その公式手順に
  従って有効化する。runops project 側で hook を自作しない。

## まず確認すること

project root で実行する:

```bash
pwd
uvx --from runops runo plugins --check
uvx --from runops runo plugins --json
```

必要に応じて project context も読む:

```bash
uvx --from runops runo context --json
```

`plugins --check` が metadata error を返す場合は、plugin install へ進む前に
project 側の `runops.toml` / simulator config / site profile の推薦 metadata を直す。
warning だけなら、内容を説明したうえで続行してよい。

## 判断すること

`runo plugins --json` から次を整理する:

- `recommendations[].name` / `display_name`
- `recommendations[].visibility`
- `recommendations[].sources`
- `recommendations[].capabilities`
- `recommendations[].install_hint`
- `recommendations[].activation_hint`
- `delegated_capabilities`
- `management.runops_installs_plugins` と `management.runops_enables_plugins`

`delegated_capabilities` を見て、作業に必要な role を優先する。例:

- `parameter-design`, `input-review`, `cookbook`
- `run-diagnose`, `output-analysis`, `visualization`
- `site-runbook`, `hpc-workflow`

## install / enable の進め方

### 1. exact command がある場合

`install_hint` に `codex plugin ...`、marketplace 登録、private plugin checkout などの
具体的なコマンドがある場合:

1. そのコマンドが現在の環境で使えるか確認する (`command -v codex` など)。
2. 実行対象が project 外なら、変更先と理由を示す。
3. ユーザーがこの skill で install / enable を依頼している場合は、危険な command でなければ実行する。
4. 実行後に `activation_hint` に従い、必要なら「新しい Codex thread を開始」などの残作業を報告する。

### 2. `/plugins` など UI 操作が必要な場合

Agent が現在の環境から plugin manager を操作できる場合は、その公式経路を使う。
操作できない場合は、plugin 名、表示名、capability、install/activation 手順を
短くまとめ、ユーザーが `/plugins` で選ぶべき項目を明示する。

### 3. private-or-gated plugin の場合

`visibility = "private-or-gated"` の plugin は、認証やローカル marketplace が必要な
ことがある。

- 認証状態は最小限だけ確認する。token は表示しない。
- private repo を clone する場合は、`install_hint` に書かれた sparse checkout などの
  低コスト手順を優先する。
- 権限不足なら、代替として project-local skill、明示的 knowledge source、
  `refs/` fallback mirror のどれを使うか提案する。

## plugin-provided hooks の扱い

ここで扱う hooks は、**plugin が明示的に提供する hook manifest / installer /
activation 手順**に限る。runops project の都合で Agent が独自 hook を設計する入口ではない。

1. `capabilities`、`install_hint`、`activation_hint`、plugin README から、
   plugin が hooks を提供しているか確認する。
2. plugin が提供する installer / enable command / hook manifest がある場合だけ使う。
   公式導線が無ければ hook は有効化しない。
3. `.codex/hooks.json` など project-local hook file を作る場合は、plugin が提供する
   template / manifest / command に基づく。hook の内容、発火条件、失敗時の影響、
   無効化方法を提示してから書く。
4. user-local plugin cache や marketplace に hook を登録する場合も、plugin の
   documented command を優先し、変更先を先に示す。
5. `~/.codex/config.toml` の `[features].codex_hooks = true` など user-local config は、
   ユーザー確認なしに編集しない。必要なら追記内容だけ提示する。

runops の既定は hooks なし。plugin が hooks を提供しない場合、submit / delete /
destructive command の扱いは `.codex/rules/runops.rules` と human gate で制御する。

## 検証

install / enable / plugin-provided hook 設定のあと、できる範囲で確認する:

```bash
uvx --from runops runo plugins --check
uvx --from runops runo plugins --json
```

注意: `runo plugins --check` は project が持つ推薦 metadata の検査であり、
user-local plugin が本当に読み込まれたかまでは保証しない。
plugin を有効化したあとに新しい Codex thread が必要な場合は、そこで再確認する。

## 完了報告

最後に次を短く報告する:

- install / enable 済みの plugin
- まだユーザー操作が必要な plugin
- plugin-provided hook を有効化したか、しなかった理由
- 新しい thread / Codex restart が必要か
- `delegated_capabilities` 上、どの role がどの plugin に委譲されるか

plugin が整ったら `{{ skill_prefix }}setup-runops` に戻り、campaign / case / survey の
初期設計へ進む。
