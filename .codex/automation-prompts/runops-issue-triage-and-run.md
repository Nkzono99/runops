# runops issue triage automation

runops の open Issue を確認し、必要なトリアージ・実装・検証・push まで進める。
HarnessOps に由来する harness / skill / agent bridge の更新も、毎回安全に取り込める範囲で確認する。

## 前提

- ユーザーとは日本語でコミュニケーションする。
- 対象リポジトリは `Nkzono99/runops`、作業ディレクトリは `C:\Users\hnjm4\Documents\Github\runops`。
- runops は HPC 環境向けの Slurm ベース実行管理 CLI であり、run ディレクトリ、`manifest.toml`、Simulator Adapter、Launcher Profile、project harness を中核にする。
- runops 本体リポジトリと、`runo init` / `runo update-harness` が生成・更新するユーザー project 側 scaffold を混同しない。
- 生成物やユーザーの未依頼変更は戻さない。既存の未コミット差分があれば内容を確認し、無関係なら触らず、作業不能な衝突がある場合だけ停止して報告する。
- commit message は英語で書く。Issue 対応 commit では可能なら `Closes #<Issue番号>` を含める。
- 高コスト・破壊的・不可逆な操作は行わない。`git reset --hard`、`git checkout -- <path>`、強制 push、手作業での scaffold 全消しは使わない。

## 最初に必ず行うこと

1. `C:\Users\hnjm4\.codex\automations\runops-issue-triage-and-run\memory.md` を読む。無ければ作成する。
2. `git status --short --branch` を確認する。
3. `gh auth status` を確認する。認証が無効なら、Issue 操作は GitHub connector で代替できる範囲だけ行い、CLI 認証が必要な作業は報告する。
4. `git pull --ff-only` で runops を最新化する。失敗したら原因を短く診断し、破壊的な復旧は行わず停止する。
5. `C:\Users\hnjm4\Documents\Github\harnessops` が存在する場合は、`git -C C:\Users\hnjm4\Documents\Github\harnessops status --short --branch` を確認し、clean または自分の作業と無関係な状態なら `git -C C:\Users\hnjm4\Documents\Github\harnessops pull --ff-only` で HarnessOps も最新化する。未コミット差分や pull 失敗がある場合は、HarnessOps 更新の取り込みだけスキップし、runops 側の Issue トリアージは続ける。
6. `AGENTS.md`、`SPEC.md`、`.agents/skills/triage/SKILL.md`、必要に応じて `.agents/skills/hops-update-harness/SKILL.md` と `.agents/skills/harnessops-bridge/SKILL.md` を確認する。

## HarnessOps 更新の取り込み

- runops は HarnessOps にリンク済みなので、HarnessOps repo を pull した後に `.harnessops/project.toml` と `.agents/skills/hops-update-harness/SKILL.md` を確認する。
- `$triage`、`$harnessops-bridge`、`$hops-update-harness` のワークフローを優先して使う。
- `hops` が PATH にあれば、runops 作業ディレクトリで次を実行する。
  - `hops doctor --check-overlay --check-records`
  - `hops migrate --check` が利用可能なら実行する。未実装・未対応なら理由を記録して続ける。
  - `hops update-harness`
- `hops` が PATH に無ければ、runops 作業ディレクトリで次の fallback を使う。
  - `uv run --with-editable C:\Users\hnjm4\Documents\Github\harnessops hops doctor --check-overlay --check-records`
  - `uv run --with-editable C:\Users\hnjm4\Documents\Github\harnessops hops migrate --check` が利用可能なら実行する。
  - `uv run --with-editable C:\Users\hnjm4\Documents\Github\harnessops hops update-harness`
- repo-local HarnessOps skills、Codex rules、Claude rules、agent bridge の再展開が必要な差分が示された場合は、`hops update-harness --agent-bridge --codex`（または同じ `uv run --with-editable ... hops` fallback）を使う。
- `.harnessops/`、`harness-feedback/`、`harness-lab/`、`harness-lab/records/` の構造は直接組み替えず、更新は `hops` CLI に委譲する。
- HarnessOps 更新で runops に差分が出た場合は、通常の変更と同じく内容を確認し、必要な検証を行い、commit / push 対象に含める。
- HarnessOps 由来の問題や改善候補を発見した場合は、必要に応じて `$harnessops-bridge` または `hops feedback` 系のコマンドで記録・ルーティングする。秘密情報やローカル固有パスを外部向け feedback に含めない。
- HarnessOps 更新が失敗しても、runops の Issue トリアージが安全に続行できるなら続ける。最終報告と memory に `hops unavailable` または失敗理由を残す。

## Issue トリアージ

1. `gh issue list --repo Nkzono99/runops --state open --limit 50 --json number,title,labels,updatedAt,createdAt,author,url` で open Issue を取得する。
2. open Issue が無ければ、実装・テスト・commit は行わず、必要なら `git push origin <current-branch>` が no-op で通ることだけ確認して終了する。
3. 各 Issue は `gh issue view <number> --repo Nkzono99/runops --json title,body,labels,comments,url` で本文とコメントを読む。
4. `AGENTS.md`、`SPEC.md`、`docs/` 配下の関連文書、該当コード、既存テストを確認する。MCP / harness / skill / automation の Issue では `.codex/README.md`、`.codex/rules/`、`.agents/skills/`、`.claude/` 側の対応箇所も確認する。
5. `$triage` 相当の判断を行い、問題、再現性、スコープ、既存実装との差分、ラベル、実装先、優先度を整理する。
6. 必要なら既存ラベルを使って `scope:*`、`type:*`、`area:*` を付与する。ラベル作成が必要な場合は、まず既存ラベル一覧を確認する。
7. 明らかな spam、悪意ある内容、完全に無関係な Issue だけ、短い理由コメントを添えて close してよい。情報不足だが正当な Issue は close せず、再現情報や期待挙動を尋ねる。

## 実装判断

- 小さく明確な Issue はその場で実装する。
- 複数の runops 利用 project に効く再現可能な摩擦は、CLI / core / template / harness の改善として扱う。
- 特定 HPC サイト、特定ローカルパス、特定 simulator の private な事情だけに依存するものは、再利用可能な抽象化が明確でない限り実装しない。
- Slurm 実コマンド、run directory の削除、archive / purge、migration、release、外部リポジトリ更新など、ユーザー環境に影響する変更は慎重に扱い、モック可能な単位に閉じ込める。
- `src/runops/templates/`、`AGENTS.md`、`CLAUDE.md`、`.agents/skills/`、`.claude/skills/`、`.codex/rules/`、`.claude/rules/`、`.codex/automation-prompts/` はユーザー向け interface なので、変更時は対応する docs、skill、rule、migration note の drift を点検する。
- CLI 名、project schema、manifest schema、analysis artifact schema、MCP contract、harness contract に影響する変更では、必要に応じて `SPEC.md`、`docs/migrations/v0.md`、`docs/` 配下の仕様文書を更新する。
- 仕様判断が大きい Issue は無理に実装せず、Issue コメントや最終報告で判断待ちにする。

## 検証

- 変更範囲に応じて最小十分な検証を選ぶ。
- Python 実装を変更したら、関連する `pytest`、`uv run ruff check src/ tests/`、必要に応じて `uv run mypy src/` を実行する。
- CLI 挙動を変更したら、該当 CLI テストと `uv run runo --help` または対象コマンドの dry-run / smoke を確認する。
- core schema、manifest、state、discovery、run creation を変更したら、関連する unit test と migration / fixture の TOML 読み書きを確認する。
- adapter / launcher / slurm を変更したら、該当 contract test と mock-based test を実行する。
- template / harness / automation prompt を変更したら、`git diff --check` を実行し、必要に応じて `hops doctor --check-overlay --check-records` と `hops update-harness --agent-bridge --codex` の結果を確認する。
- broad な変更では、`uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80` まで実行する。
- 検証が通らない場合は、原因、未解決リスク、次の作業を明記する。壊れた状態を push しない。

## commit / push

- 変更がある場合だけ、意味のある作業単位で stage / commit する。
- commit message は英語で、`fix:`, `feat:`, `docs:`, `test:`, `refactor:`, `chore:` などを使う。
- Issue 対応 commit では、可能なら body または subject に `Closes #<Issue番号>` を含める。
- commit 後に `git push origin <current-branch>` を実行する。
- Issue を手動 close する場合は、対応 commit hash と変更要約をコメントに含める。
- 自分が作った automation commit または memory に明確に記録された automation 継続作業以外は、勝手に push しない。

## 終了時

- `git status --short --branch` を確認する。
- `C:\Users\hnjm4\.codex\automations\runops-issue-triage-and-run\memory.md` に、実行時刻、runops pull 結果、HarnessOps pull / update 結果、確認した Issue、対応内容、検証結果、commit / push 結果、残課題を簡潔に追記する。
- 最終応答は、何を確認し、何を変更し、何が未対応かを短く日本語でまとめる。
- 最終応答の最後に、要約を入れた `::inbox-item{...}` directive を 1 つだけ出す。
