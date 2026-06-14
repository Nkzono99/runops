---
name: update-docs
description: "Reflect code changes into documentation. Scan recent commits or staged changes, identify which docs need updating, and apply the updates. Use after implementing features, fixing bugs, or adding skills/commands."
---

# ドキュメント反映

`$update-docs` はコード変更に伴うドキュメント更新を行うスキル。
機能追加・修正・スキル追加の後に呼ぶことで、ドキュメントの整合性を保つ。

## 対象ドキュメント

### このリポジトリ (runops 開発者向け)

| ファイル | 内容 | 更新タイミング |
|---------|------|---------------|
| `AGENTS.md` | Codex が最初に読む短い入口 | 上位方針・参照先・ハーネス責務が変わった時 |
| `.codex/rules/commands.md` | 全コマンド一覧 | CLI 引数追加・変更時 |
| `.codex/rules/dev-workflow.md` | 開発ワークフロー | ビルド手順・品質ゲート変更時 |
| `.codex/rules/architecture.md` | アーキテクチャ原則 | レイヤ構造変更時 |
| `docs/toml-reference.md` | TOML 設定リファレンス | case.toml / survey.toml 等のフィールド追加時 |
| `docs/extending.md` | 拡張ガイド | Adapter / Launcher の追加方法変更時 |
| `docs/agent-user-guide.md` / `docs/get-started-with-agent.md` | Agent 向けワークフロー | plugin 委譲・初期導線変更時 |
| `docs/layers/*.md` | レイヤ別設計・運用 | knowledge / harness / interface 変更時 |
| `src/runops/sites/*.md` | サイト固有ドキュメント | サイト機能追加・制限事項更新時 |

### プロジェクト側ハーネス (runops ユーザー向け)

| テンプレート | 内容 | 更新タイミング |
|------------|------|---------------|
| `src/runops/templates/harness/codex/AGENTS.md.j2` | プロジェクト側 AGENTS.md | コマンド体系変更時 |
| `src/runops/templates/harness/claude/CLAUDE.md.j2` | プロジェクト側 CLAUDE.md | コマンド体系変更時 |
| `src/runops/templates/harness/shared/rules/*.md.j2` | 共通 rule | ワークフロー・cookbook 変更時 |
| `src/runops/templates/skills/*/SKILL.md` | プロジェクト側スキル | 定型作業・コマンド変更時 |

## 手順

### 1. 変更内容を把握する

```bash
# 直近のコミットから (デフォルト)
git log --oneline HEAD~5..HEAD

# または未コミットの変更
git diff --stat
```

### 2. 影響するドキュメントを特定する

変更の種類と対応するドキュメント:

| 変更の種類 | 更新対象 |
|-----------|---------|
| CLI オプション追加・変更 | `commands.md`, `toml-reference.md` |
| TOML フィールド追加 | `toml-reference.md` |
| 新スキル追加 | プロジェクト側テンプレートの AGENTS.md / CLAUDE.md (スキル一覧があれば) |
| サイト固有の変更 | `src/runops/sites/<site>.md` |
| Adapter / Launcher 追加 | `docs/extending.md` |
| アーキテクチャ変更 | `architecture.md` |

### 3. ドキュメントを更新する

各対象ファイルを読み、変更を反映する。

### 4. 整合性チェック

- コマンドの `--help` 出力とドキュメントが一致しているか
- TOML フィールドの型・デフォルト値が正しいか
- スキルの description がファイル内容と一致しているか

## 注意事項

- ドキュメントの書き方や文体は既存部分に合わせる
- 日本語ドキュメントと英語ドキュメントの両方を更新する
- ハーネス二重構造に注意: 開発者向け (`.claude/`, `.codex/`, `.agents/skills/`) とプロジェクト側 (`src/runops/templates/`) は別物
- `AGENTS.md` / `CLAUDE.md` は 150 行程度を目安に短く保つ。長いコマンド表は rules、定型手順は skills に置く
