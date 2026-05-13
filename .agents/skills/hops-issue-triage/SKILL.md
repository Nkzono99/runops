---
name: hops-issue-triage
description: GitHub issue や外部issueを HarnessOps の feedback/lab ループに取り込み、評価ケース、仮説、判断へ進めるときに使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

GitHub issue の取得やコメント確認は GitHub plugin または `gh` に任せます。この skill は issue を HarnessOps の正本レコードへ載せるために使います。

`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。状態変更は `hops` CLI に委譲します。

手順:

1. `hops doctor --check-overlay` を実行する。
2. GitHub issue の本文、コメント、ラベル、再現情報、非公開リスクを確認する。
3. 対象 repository が `harness-lab` を持つ target/meta repo なら issue を imported feedback にする。

```bash
hops feedback import --issue <issue-number> --repo <owner/repo>
```

4. project repo 側で観測した失敗なら、issue をそのまま転載せず、失敗として記録してから routing する。

```bash
hops add-failure --target <target> ...
hops route --record F0001
hops add-feedback --from F0001 --target <target>
hops feedback export --target <target> --sanitize
```

5. imported feedback を改善候補として扱う場合は評価ケース化する。

```bash
hops lab new-eval-case --from FB0001
hops propose --from E0001
```

6. 実装後は `hops eval --case <Eid> --manual` を使い、証拠、回帰リスク、ガードパスが揃うまで `adopted` 判断を作らない。

GitHub issue は入力です。HarnessOps の正本は `harness-feedback/` または `harness-lab/` のレコードです。未サニタイズ情報、ローカルパス、private term を外部向け bundle や issue コメントへ戻さない。
