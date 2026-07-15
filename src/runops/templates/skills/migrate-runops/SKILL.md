---
name: migrate-runops
description: Apply runops project-state migrations from docs/migrations after updating runops. Use when update-runops or a release note says a project layout, config schema, manifest, analysis artifact, harness, or knowledge format changed.
---

# runops project-state migration を適用する

`{{ skill_prefix }}migrate-runops` は、runops 更新後に project 側の状態を
release note / migration guide の手順へ合わせるための skill です。

`{{ skill_prefix }}update-runops` は runops 本体と harness を versioned upgrade chain で
更新する入口。この skill は、そのあとに必要な project file / generated index / schema の
移行だけを扱います。

## Version policy

- v0 系では後方互換性を強く維持しない。breaking change は許容するが、
  project-state に影響するものは migration guide に書かれている必要がある。
- v1 以降は SemVer を尊重する。CLI / project schema / manifest / analysis artifact
  schema の breaking change は major version bump と migration guide を必要とする。
- guide にない破壊的変更や schema rewrite を推測で実行しない。

## 入力として読むもの

必要な範囲で読む:

- `uvx --from runops runo context --json`
- `uvx --from runops runo --version`
- `uvx --from runops runo update-harness --plan`
- `uvx --from runops runo migrate list`
- release note または migration guide
- migration item が指定する project file
- `research/CURRENT.md`、最近の journal segment、relevant result README

## 手順

### 1. 対象 version と guide を特定する

```bash
uvx --from runops runo --version
uvx --from runops runo update-harness --plan
uvx --from runops runo migrate list
```

`update-harness --plan` は harness の versioned chain を確認するためのもの。
project-state migration は migration guide と `migrate list/show/apply` で別途確認する。
project に runops source checkout があるとは限らない。必要な場合は release note、
installed package の generated guide、または別 checkout の `docs/migrations/` を読む。

### 2. runner 結果と migration checklist を作る

まず update-runops で実行した chain を確認する:

```markdown
Runner plan:
- harness: 0.8.0 -> 0.8.2 -> 0.9.0
- result: applied / deferred / failed
```

そのうえで project-state migration item ごとに次を判定する:

各 item について次を判定する:

```markdown
| ID | Applies | Type | Human gate | Action |
|----|---------|------|------------|--------|
| M0-0001 | yes/no/unknown | compatible-generated | no | apply/skip/defer |
```

`unknown` は勝手に適用しない。必要な file を追加で確認する。

### 2.5. CLI で定型適用できるか確認する

登録済み migration は CLI で確認・適用できる:

```bash
uvx --from runops runo migrate list
uvx --from runops runo migrate show M0-0001
uvx --from runops runo migrate apply M0-0001 --dry-run
uvx --from runops runo migrate apply M0-0001
```

CLI で扱えるのは、定型化された idempotent な migration だけ。
CLI 未対応、判断が必要、または destructive-human-gate の item は、この skill で
guide を読みながら扱う。

### 3. Type ごとに扱う

- `compatible-generated`: 既存 project を壊さない生成・index 作成。scope を説明してから適用する。
- `manual-edit`: 小さな手編集。diff を示して validation まで実行する。
- `breaking-manual`: 新仕様に移さないと壊れる変更。手順と影響範囲を説明し、
  重要 file を読む前後で git 状態を確認する。
- `destructive-human-gate`: 削除、purge、archive、不可逆 rewrite。必ず人間の確認を得る。

### 4. 適用する

guide の `Migration` に書かれた command / file edit だけを実行する。
guide にない補完が必要なら migration を止め、project 固有情報を除いた docs gap の
issue 下書きを残す。

### 5. 検証する

最低限:

```bash
uvx --from runops runo doctor
uvx --from runops runo context --json
uvx --from runops runo lint
```

加えて item の `Validation` に書かれた command / file check を実行する。
解析成果物の migration では、対象の `artifacts.toml` が実在成果物を指しているか確認する。

### 6. journal に記録する

適用 / skip / defer を lab notebook に残す:

```bash
runo research append "runops migration" "$(cat <<'EOF'
Context: runops target version=<version>.
Applied:
- M0-0001: <what changed>
Skipped:
- M0-0002: not applicable because <reason>
Validation:
- runo doctor: pass/fail
- runo context --json: pass/fail
- runo lint: pass/fail/warnings
Follow-up:
- <upstream issue candidate or none>
EOF
)"
```

研究判断が変わった場合だけ `research/CURRENT.md` も更新する。
通常の runops migration は research agenda の対象ではない。

## 重要ルール

- migration guide にない破壊的変更を実行しない。
- project 固有の `research/`, `campaign.toml`, `cases/`, `runs/` を
  runops upstream の source と混ぜない。
- runops 本体に local patch がある場合は、先に `{{ skill_prefix }}patch-runops`
  で別 checkout の branch / commit / upstream disposition を整理する。
- validation できない migration は `defer` として記録し、理由を書く。
- private path、unpublished result、site 秘密を issue / PR / upstream docs に載せない。

## 報告フォーマット

最後にこの形で報告する:

```markdown
## Migration result

- Target version:
- Guide:
- Runner plan:
- Chain applied:
- Applied:
- Skipped:
- Deferred:
- Human gates:
- Validation:
- Notes entry:
- Feedback candidates:
```
