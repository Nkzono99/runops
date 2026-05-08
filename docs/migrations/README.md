# Migration Guides

このディレクトリは、runops の更新で project 側の状態や file format に移行が必要に
なったときの正本です。

`update-runops` は runops 本体と harness を更新する入口、`migrate-runops` はこの
guide に従って project 側の migration を適用する入口です。

定型 migration は CLI でも適用できます。基本形は次です。

```bash
# 登録済み migration を確認
runo migrate list
runo migrate list --version v0
runo migrate show M0-0001

# 事前確認
runo migrate apply M0-0001 --dry-run

# 適用
runo migrate apply M0-0001
```

Migration の正本 ID は `M0-0001` の形式です。
`apply` / `show` は `runo migrate apply v0 0001` のように version と number を
分けても指定できます。`VERSION` は `v0`, `0`, `0.7.0` のような major を
特定できる値を受け付けます。`NUMBER` は `1`, `0001`, `M0-0001` のいずれでも指定できます。
不可逆または human gate 付きの migration は、guide を読んだうえで `--yes` を付けて実行します。

## Version policy

runops は現在 private / pre-public な CLI として開発しているため、v0 系では内部 API、
CLI option、project file format の後方互換性を強く維持しません。
ただし、既存 project の状態に影響する breaking change は migration item として
ここに残します。

- `0.x`: breaking change は許容する。長期互換 layer は原則作らず、migration guide で移行する。
- `1.x` 以降: CLI、project schema、manifest、analysis artifact schema を public contract とみなす。
  breaking change は major version bump と migration guide を必要とする。
- patch release: 原則として移行不要な bug fix に限定する。

つまり、v0 では「後方互換を保つ」より「移行方法を明示する」を優先します。
v1 以降は SemVer に合わせ、互換を切るなら major version を上げます。

## File layout

major version ごとに migration guide を分けます。

```text
docs/migrations/
  README.md
  v0.md
  v1.md
```

minor / patch ごとの項目は、対応する major guide の中に新しい順または適用順で追加します。
肥大化した場合は `v1/1.2.md` のように分割してもよいですが、入口は常に
`docs/migrations/v<major>.md` に置きます。

## Migration item format

project 側の手作業や Agent 作業が必要な変更は、次の情報を持つ item として書きます。

```markdown
## M0-0001 Short title

- Since: 0.7.0
- Type: compatible-generated / manual-edit / breaking-manual / destructive-human-gate
- Impact: notes / research / run-manifest / analysis-artifact / harness / config / other
- Applies when:
- What changed:
- Migration:
- Validation:
- Rollback:
- Human gate:
```

`Type` の意味:

- `compatible-generated`: 既存 project は壊れないが、再生成や index 作成で新仕様を使える。
- `manual-edit`: 小さな手編集が必要。削除や不可逆操作は含まない。
- `breaking-manual`: 旧仕様のままでは新しい runops が正しく扱えない。migration が必要。
- `destructive-human-gate`: 削除、purge、archive、schema rewrite など不可逆に近い操作。
  必ず人間の確認を挟む。

## Adding CLI-backed migrations

定型化できる migration は `src/runops/core/migrations/` に実装します。

```text
src/runops/core/migrations/
  models.py      # Migration / MigrationContext / MigrationResult
  registry.py    # id 解決と実行
  v0.py          # v0 の migration handlers
  v1.py          # v1 以降は必要になったら追加
```

新しい item を CLI で実行可能にする手順:

1. `docs/migrations/v<major>.md` に migration item を追加する。
2. `src/runops/core/migrations/v<major>.py` に idempotent な handler を追加する。
3. `registered_migrations()` に `Migration(version="v0", number="0003", ...)` を登録する。
4. `tests/test_core/test_migrations.py` と `tests/test_cli/test_migrate.py` に dry-run / apply のテストを追加する。

CLI-backed migration は、同じ project に複数回実行しても壊れないことを前提にします。
判断が必要な migration は CLI handler にせず、guide と `migrate-runops` skill で扱います。

## Update workflow

1. `update-runops` で `tools/runops` と harness を更新する。
2. `tools/runops/docs/migrations/README.md` と対象 major の guide を読む。
3. current project に該当する item があれば `runo migrate apply <id> --dry-run`
   で確認し、定型適用できるものは `runo migrate apply <id>` で実行する。
   CLI 未対応または判断が必要なものは `migrate-runops` を使う。
4. migration の適用 / skip / 保留を `notes/YYYY-MM-DD.md` に残す。
5. `runo doctor` と item ごとの validation を実行する。

Migration guide にない破壊的変更を推測で実行してはいけません。
guide が足りない場合は、まず `feedback-runops` で docs gap として扱います。
