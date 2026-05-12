# runops ワークフロールール

このファイルは、以前 PreToolUse hook (`protect-files.sh`, `guard-bash.sh`,
`approve-run.sh`) で強制していた挙動を、AI エージェントが読む rule として
記述する。permissions.deny で機械的に止められるものは settings.json に
任せ、ここでは「Agent が判断すべき振る舞い」を明示する。

## ファイル操作の制約

以下は permissions.deny でも止めるが、Bash 経由 (cp, mv, rm, sed -i,
リダイレクト等) では permissions が効かないので、Agent 側の自制で守る:

- run ディレクトリ (`Rxxxx/`) は手で作らない
- `manifest.toml` は手動編集も Bash 書き込みもしない
- `Rxxxx/input/*` を直接作らない (case template から再生成する)
- `Rxxxx/submit/job.sh` は手書きしない (runops が生成する)
- run は必ず `runo runs create` または `runo runs sweep` で生成する
- `work/` の出力は読み取り専用扱い (移動・削除しない)
- `.runops/knowledge/` の自動生成物は手で整形しない
- `.runops/insights/` と `.runops/facts.toml` は直接編集せず、
  `runo knowledge save` / `runo knowledge add-fact` を使う
- `SITE.md` は site profile 由来の生成ドキュメントとして直接編集しない
- `refs/` 配下は外部リポジトリのミラーなので書き込まない
- `runs/**/input/*` を緊急修正した場合は、同じ修正を上流の case へ戻す

## runops 本体の編集

- 通常の project には `tools/runops/` がない前提で作業する
- runops 本体を修正する必要がある場合は、project の研究作業とは別の
  source checkout を用意し、修正・検証・PR 化を分けて扱う
- project 側では installed package の version と
  `.runops/knowledge/runops/` の生成済み guide を確認入口にする

## venv

- **runops コマンド実行前に `.venv/` を activate する**

## case 作成

- **case は `runo case new <name> -s <simulator>` で生成する**
  (`cases/<sim>/` に自動配置)
- 生成された `case.toml` や入力テンプレートの編集は自由

## ジョブ投入の確認フロー

`runo runs submit` は破壊的操作ではないが、HPC 資源・queue・quota に影響する。
permissions では allow し、Agent 側の workflow rule として以下を守る:

- 実行前に **投入内容 (コマンド・対象 run・queue・QOS・資源量) をユーザーに提示**
  してから submit を呼ぶ
- partition override: `-qn <name>`, QOS override: `--qos <name>`
- `runo runs submit --all` は CLI 側でも確認する。会話上で明示確認済みの場合だけ `--yes` を使う
- `--dry-run` と `--help` は確認用なのでそのまま実行してよい
- 承認なしに実ジョブ投入を繰り返し試行しない
- policy や環境で bulk submit が止まった場合、個別 submit に分解して迂回しない。
  止まった理由と予定していた submit command をユーザーへ返す
- 一度の submit で複数 run が走る (例: `--all`) ときは特に慎重に説明する

## 設定ファイルの変更

以下は permissions.ask でユーザー承認が必要なファイル:
`runops.toml`, `simulators.toml`, `launchers.toml`, `CLAUDE.md`,
`AGENTS.md`, `**/CLAUDE.md`, `**/AGENTS.md`, `.claude/settings.json`,
`.claude/hooks/**`, `.codex/config.toml`, `.codex/rules/**`. 変更前に意図と
差分を提示する。

## コミットの義務

意味のある作業単位ごとに必ず Git コミットして履歴を残す。詳細は CLAUDE.md
の「進捗のコミット (義務)」セクションを参照。最低限以下のタイミングで
コミットする:

- campaign / case / survey の新規作成・大幅変更
- `runo runs sweep` で新しい run を生成したとき
- 解析結果・知見を保存したとき
- runops 本体の別 checkout で修正してテストが通ったとき
- `runo runs submit` の前 (投入前のスナップショット)

## 知見の記録

- 実験の知見・結果は Agent の memory ではなく `/learn` で保存する
- 保存先: `.runops/insights/`, `.runops/facts.toml`
- 外部 source から来た候補 fact は `.runops/knowledge/candidates/facts/` に入る
- 候補 fact を採用するときは `runo knowledge promote-fact <source>:<fact_id>` を使う
- `high` confidence は複数 run の再現か deterministic 確認がある場合だけ使う

## 解析 scratch

- 試行中の図・ノート・一時集計は `runs/**/analysis/scratch/` に置く
- `analysis/summary.json` や curated figure を scratch 出力で上書きしない
