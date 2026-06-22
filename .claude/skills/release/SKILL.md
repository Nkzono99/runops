---
name: release
description: "Prepare and publish a new runops release from main. Bump version, sync __init__.py, draft Japanese release notes, push main, tag the release commit, create GitHub Release, and verify PyPI publish."
---

# runops リリース

`/release` は新しいバージョンの runops をリリースするスキル。

## リリースノート方針

- リリースノートは**必ず日本語**で書く
- コード、コマンド、commit prefix、識別子は英語のままでよい
- annotated tag と GitHub Release 本文の両方に、日本語の要約と本文を残す
- tag を push しただけで終わらせない。GitHub Release が存在し、本文が空でないことまで確認する

## 使い方

```
/release patch      # 0.2.1 -> 0.2.2
/release minor      # 0.2.1 -> 0.3.0
/release major      # 0.2.1 -> 1.0.0
/release 0.3.0      # 明示的にバージョン指定
```

引数なしで呼んだ場合は、変更内容から bump レベルを自動判定し、
main release commit → main push → CI 確認 → tag → GitHub Release → publish 確認まで一気通貫で実行する。

現在は個人開発のため main-first。release commit は `main` 上で作り、
品質ゲートと CI green を確認してから、その release commit に tag を切る。
`--force`、non-fast-forward push、`--no-verify` は使わない。

## 手順

### 1. リリース可否を確認する

```bash
# 未コミットの変更がないか
git status --porcelain

# テストが全て通るか
uv run pytest tests/ -x -q

# lint / type check
uv run ruff check src/ tests/
uv run mypy src/
```

品質ゲートが通らなければリリースを中止する。

### 2. 変更内容を把握する

```bash
# 前回リリースタグからの変更
git log $(git describe --tags --abbrev=0 2>/dev/null || echo HEAD~20)..HEAD --oneline
```

commit message から以下を分類する:

- **Breaking changes** (`feat!:`, `BREAKING CHANGE`) → major bump 候補
- **New features** (`feat:`) → minor bump 候補
- **Bug fixes** (`fix:`) → patch bump 候補
- **Other** (`refactor:`, `test:`, `docs:`, `chore:`)

### 2.5. リリースノートを日本語で下書きする

前回タグからの変更を整理し、少なくとも以下を日本語でまとめる:

- **概要**: このリリースで何が良くなったか
- **主な追加機能**: `feat:` に対応するユーザー向け変更
- **主な修正**: `fix:` に対応する振る舞い修正
- **補足**: `refactor:` `docs:` `chore:` など必要なもの

短い 1 段落ではなく、後で tag message や GitHub Release にそのまま転用できる
箇条書きの下書きにしておく。

### 3. バージョンを決定する

引数で指定されていればそれを使う。なければ以下のルールで自動判定する:

- `feat!:` or `BREAKING CHANGE` あり → **major**
- `feat:` あり → **minor**
- `fix:` のみ → **patch**
- `docs:` / `chore:` のみ → **patch**

### 4. バージョンを更新する

2 箇所を同時に更新する (**ずれ防止**):

1. `pyproject.toml` の `version = "X.Y.Z"` — pip / PyPI が参照する正本
2. `src/runops/__init__.py` の `__version__ = "X.Y.Z"` — ランタイム参照

### 5. main で release commit を作る

`main` を最新化し、未コミットの実装・docs 変更は先に論理単位で commit しておく。
最後に version bump commit を作る。

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git add pyproject.toml src/runops/__init__.py
git commit -m "chore: bump version to X.Y.Z"
```

### 6. main を push し、CI を確認する

main は direct push する。GitHub ruleset は default branch の削除と
non-fast-forward を防ぐ。push 後に CI green を確認する。

```bash
git push origin main
gh run list --branch main --limit 5
gh run watch <run-id> --exit-status
```

CI が失敗した場合は、同じ `main` 上で修正 commit を積み、再度 `git push origin main`
してから release tag へ進む。

### 7. main の release commit に tag を付けて公開する

tag は `main` の release commit に付ける。
tag push により `.github/workflows/publish.yml` が起動し、CI が自動で PyPI にパブリッシュする。

```bash
git pull --ff-only origin main
git tag -a vX.Y.Z -m "<日本語のリリースノート要約>"
git push origin vX.Y.Z
```

`git pull --ff-only origin main`、`git tag -a`、`git push origin vX.Y.Z` は順に実行する。
tag が release commit 以外を指すと publish が壊れる。

### 8. GitHub Release を作成する

tag を push したら、同じ tag に対する GitHub Release を必ず作成する。
annotated tag に日本語のリリースノートを入れている場合は、それをそのまま使う:

```bash
gh release create vX.Y.Z \
  --verify-tag \
  --title "runops X.Y.Z" \
  --notes-from-tag
```

既に Release が存在するが本文が空、または古い場合は、下書き済みの本文で更新する:

```bash
gh release edit vX.Y.Z \
  --title "runops X.Y.Z" \
  --notes-file release-notes.md
```

古い tag の Release を後から作るときは、最新 release 扱いにならないよう必要に応じて
`--latest=false` を付ける。最新の通常リリースだけを Latest にする。

### 9. 確認

```bash
gh run list --workflow=publish.yml --limit 1
gh release view vX.Y.Z --json tagName,name,body,url
```

`gh release view` の `body` が空ならリリース作業は未完了。

## 引数なしの場合

変更内容を分類し、bump レベルを自動判定して、リリースまで実行する。
具体的には:

1. 前回タグからのコミットを分類 (breaking / feat / fix / other)
2. bump レベルを自動判定
3. 日本語のリリースノート草案を作る
4. 変更サマリとバージョンをユーザーに提示して確認
5. 明示依頼または確認が取れていれば手順 4〜9 を順に実行 (バージョン更新 → main push → CI 確認 → tag push → GitHub Release 作成)
