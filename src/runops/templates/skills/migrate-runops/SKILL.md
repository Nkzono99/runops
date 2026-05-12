---
name: migrate-runops
description: Apply runops project-state migrations from docs/migrations after updating runops. Use when update-runops or a release note says a project layout, config schema, manifest, analysis artifact, harness, or knowledge format changed.
---

# runops project-state migration を適用する

`{{ skill_prefix }}migrate-runops` は、runops 更新後に project 側の状態を
`tools/runops/docs/migrations/` の手順へ合わせるための skill です。

`{{ skill_prefix }}update-runops` は runops 本体と harness を更新する入口。
この skill は、そのあとに必要な project file / generated index / schema の移行だけを扱います。

## Version policy

- v0 系では後方互換性を強く維持しない。breaking change は許容するが、
  project-state に影響するものは migration guide に書かれている必要がある。
- v1 以降は SemVer を尊重する。CLI / project schema / manifest / analysis artifact
  schema の breaking change は major version bump と migration guide を必要とする。
- guide にない破壊的変更や schema rewrite を推測で実行しない。

## 入力として読むもの

必要な範囲で読む:

- `runo context --json`
- `tools/runops/pyproject.toml` または `runo --version`
- `tools/runops/docs/migrations/README.md`
- `tools/runops/docs/migrations/v<major>.md`
- migration item が指定する project file
- 最近の `notes/YYYY-MM-DD.md` と relevant `research/agenda.md`

## 手順

### 1. 対象 version と guide を特定する

```bash
runo --version
sed -n '1,220p' tools/runops/docs/migrations/README.md
sed -n '1,260p' tools/runops/docs/migrations/v0.md
```

`tools/runops` が project にない場合は、current checkout の `docs/migrations/` を読む。

### 2. migration checklist を作る

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
runo migrate list
runo migrate show M0-0001
runo migrate apply M0-0001 --dry-run
runo migrate apply M0-0001
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
guide にない補完が必要なら、migration を止めて `{{ skill_prefix }}feedback-runops`
候補として HarnessOps record / docs gap 下書きを残す。

### 5. 検証する

最低限:

```bash
runo doctor
runo context --json
runo lint
```

加えて item の `Validation` に書かれた command / file check を実行する。
解析成果物の migration では、対象の `artifacts.toml` が実在成果物を指しているか確認する。

### 6. note に記録する

適用 / skip / defer を lab notebook に残す:

```bash
runo notes append "runops migration" - <<'EOF'
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
- <feedback-runops HarnessOps feedback candidate or none>
EOF
```

研究判断が変わった場合だけ `{{ skill_prefix }}research-agenda` も使う。
通常の runops migration は research agenda の対象ではない。

## 重要ルール

- migration guide にない破壊的変更を実行しない。
- project 固有の `notes/`, `research/`, `campaign.toml`, `cases/`, `runs/` を
  runops upstream の source と混ぜない。
- `tools/runops` に local patch がある場合は、先に `{{ skill_prefix }}patch-runops`
  で整理する。
- validation できない migration は `defer` として記録し、理由を書く。
- private path、unpublished result、site 秘密を issue / PR / upstream docs に載せない。

## 報告フォーマット

最後にこの形で報告する:

```markdown
## Migration result

- Target version:
- Guide:
- Applied:
- Skipped:
- Deferred:
- Human gates:
- Validation:
- Notes entry:
- Feedback candidates:
```
