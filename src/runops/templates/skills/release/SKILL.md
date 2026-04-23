---
name: release
description: "Tag a project milestone, archive completed runs, and record a release snapshot in lab notebook. Use when a campaign phase or experiment batch reaches a natural checkpoint."
---

# プロジェクトリリース (マイルストーンタグ)

`/release` はシミュレーションプロジェクトのマイルストーンを
git tag として記録するスキル。論文投稿・報告書提出・キャンペーン
区切りなどのタイミングで使う。

## リリースノート方針

- リリースノートは**必ず日本語**で書く
- コマンド、識別子、ファイル名は英語のままでよい
- annotated tag や lab notebook に残す要約も日本語で統一する

## 使い方

```
/release v1.0 "初期パラメータサーベイ完了"
/release v2.0 "追加実験 + 解析完了"
```

引数なしで呼んだ場合は、現在の状態を確認してリリース可否を判定する。

## 手順

### 1. 現在の状態を確認する

```bash
# 全 run の状態を確認
runo runs list . 2>/dev/null || echo "no runs found"

# 未コミットの変更
git status --porcelain

# 既存タグ
git tag --list 'v*' --sort=-v:refname | head -5
```

以下を確認する:
- 全ての run が terminal 状態 (completed / failed / cancelled) か
- 未コミットの変更がないか
- 解析結果が notes/ や analysis/ に記録されているか

### 2. リリースノートを作成する

前回タグからの変更を把握し、リリースノートを整理する:

```bash
git log $(git describe --tags --abbrev=0 2>/dev/null || echo HEAD~30)..HEAD --oneline
```

リリースノートに含める情報:
- **目的**: このマイルストーンで何を達成したか
- **実行した run**: case / survey の概要と結果
- **主要な知見**: `.runops/insights/` や `notes/` から
- **データの場所**: 重要な出力ファイルのパス
- **次のステップ**: 残タスクや次のキャンペーン

上の項目は日本語で記述し、tag message や notebook 記録へ再利用できる形で
整理しておく。

### 3. 完了 run をアーカイブする (任意)

```bash
# completed な run をアーカイブ
runo runs archive --all .
```

### 4. タグを作成する

```bash
git add -A
git commit -m "chore: prepare release vX.Y — <概要>"
git tag -a vX.Y -m "<リリースノート概要>"
```

### 5. lab notebook に記録する

```bash
runo notes append "release vX.Y" "<リリースノート概要>"
```

### 6. push する (ユーザー確認後)

```bash
git push origin main --tags
```

## 引数なしの場合

リリース準備状況を診断して報告する:

```
## リリース準備状況

現在のタグ: v1.0 (2026-03-15)
前回から 42 commits

### Run 状態
- completed: 30
- failed: 2 (要確認)
- running: 0
- created: 0

### 未コミットの変更: なし

### 知見の記録
- insights: 5 件
- facts: 12 件
- notes: 8 日分

→ リリース可能です。`/release v2.0 "<概要>"` で実行できます
```
