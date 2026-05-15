---
name: hops-issue-triage
description: GitHub issue や外部issueを HarnessOps の feedback/lab ループに取り込み、評価ケース、仮説、判断へ進めるときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

GitHub issue の取得やコメント確認は GitHub plugin または `gh` に任せます。この skill は issue を HarnessOps の正本レコードへ載せるために使います。

`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。状態変更は `hops` CLI に委譲します。

手順:

1. `hops doctor --check-overlay` を実行する。
2. issue 番号、URL、bundle が渡されていない場合は、現在の GitHub repo の open issue を探索して triage report を作る。GitHub plugin または `gh issue list --state open` を使い、必要に応じて `gh issue view` で本文、コメント、ラベル、再現情報を確認する。
3. 特定 issue が渡された場合も、GitHub issue の本文、コメント、ラベル、再現情報、非公開リスクを確認する。

## 引数なしの open issue triage

入力 issue がない場合、この skill は「何もしない」で終えず、open issue を探索する。

1. `git remote -v`、GitHub plugin、または automation prompt から `<owner/repo>` を決める。
2. open issue を取得する。

```bash
gh issue list --repo <owner/repo> --state open --limit 50 --json number,title,labels,updatedAt,url,author
```

3. 優先度が高そうなもの、閉じる候補、情報不足のものは詳細を見る。

```bash
gh issue view <number> --repo <owner/repo> --json number,title,body,labels,comments,createdAt,updatedAt,url,author
```

4. 次の triage report を返す。

- 対応推奨 (高): regression、security/privacy risk、broken release/update、user-blocking failure、明確な再現がある重要 issue。
- 対応推奨 (中): docs/skill/workflow friction、再現可能だが限定的な不具合、優先度中の改善。
- 保留 / 要議論: 設計判断が必要、再現情報が不足、scope が曖昧、private context の確認が必要。
- close 推奨: duplicate、解決済み、scope 外、spam、malicious、unrelated、wontfix が妥当な issue。

各 item には `issue`, `summary`, `evidence`, `missing_info`, `recommended_hops_action`, `remote_action_allowed` を短く含める。

spam / malicious / unrelated は close 候補として扱うが、本文を HarnessOps record や外部コメントへ必要以上に転載しない。issue close、comment、label 変更は、人間または automation prompt が明示的に許可した場合だけ実行する。権限がなければ close/comment draft を報告に残す。

## HarnessOps への取り込み

1. 対象 repository が `harness-lab` を持つ target/meta repo なら issue を imported feedback にする。

```bash
hops feedback import --issue <issue-number> --repo <owner/repo>
```

2. project repo 側で観測した失敗なら、issue をそのまま転載せず、失敗として記録してから routing する。

```bash
hops add-failure --target <target> ...
hops route --record F0001
hops add-feedback --from F0001 --target <target>
hops feedback export --target <target> --sanitize
```

3. imported feedback を改善候補として扱う場合は評価ケース化する。

```bash
hops lab new-eval-case --from FB0001
hops propose --from E0001
```

4. 実装後は `hops eval --case <Eid> --manual` を使い、証拠、回帰リスク、ガードパスが揃うまで `adopted` 判断を作らない。

## 完了時の issue close 作法

- 実装 commit / PR で閉じる場合は、権限がある時だけ commit message または PR body に `Closes #N` を入れる。
- 手動 close comment では、対応内容、証拠、validation、関連 commit/PR を短く書く。
- wontfix / scope 外で閉じる場合は、理由、代替案、再オープン条件を短く書く。
- remote action 権限がない場合は、実行せず、コメント案と close 推奨理由を報告する。

GitHub issue は入力です。HarnessOps の正本は `harness-feedback/` または `harness-lab/` のレコードです。未サニタイズ情報、ローカルパス、private term を外部向け bundle や issue コメントへ戻さない。
