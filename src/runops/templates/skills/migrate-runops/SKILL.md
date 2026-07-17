---
name: migrate-runops
description: Use when the requested outcome is an applied, skipped, or deferred project-state migration identified by a runops release or migration guide.
---

# guideに従ってproject stateを移行する

## 実行契約

- **Goal**: target versionに該当するmigration itemをapply / skip / deferに確定する
- **Done**: target、guide、各itemのdisposition、変更、validation、human gateを報告できる
- **Budget**: current-to-targetのversion範囲と該当itemだけ
- **Invariant**: guideにないrewriteを推測せず、destructive changeとunknown applicabilityをHuman gateなしで進めない

`{{ skill_prefix }}update-runops`はtool / harness更新、このskillはproject file、schema、index、
analysis artifactなどのstate migrationだけを扱う。

## Evidence routing

```bash
uvx --from runops runo --version
uvx --from runops runo update-harness --plan
uvx --from runops runo migrate list
uvx --from runops runo migrate show <id>
```

選択itemのrelease note、generated guide、または`docs/migrations/`と、itemが指定するfileだけを読む。

| migration type | route |
|---|---|
| `compatible-generated` | scope確認 → CLI dry-run / apply |
| `manual-edit` | guideの小さなdiff → validation |
| `breaking-manual` | impactとrollbackを示してcheckpoint |
| `destructive-human-gate` | 対象・損失・rollbackを示して明示承認 |

```bash
uvx --from runops runo migrate apply <id> --dry-run
uvx --from runops runo migrate apply <id>
```

CLIは登録済みのidempotent migrationだけに使う。applicabilityが`unknown`、CLI未対応、guide不足なら
適用せずdeferする。local patchが前提なら先に`{{ skill_prefix }}patch-runops`でsource checkoutを
整理する。

## Validation

```bash
uvx --from runops runo doctor
uvx --from runops runo context --json
uvx --from runops runo lint
```

item固有validationを加え、analysis artifactではindexが実体を指すことも確認する。migration outcomeの
記録が依頼に含まれる場合だけ`runo research append`を使う。private path、未公開result、site秘密を
feedbackへ含めない。
