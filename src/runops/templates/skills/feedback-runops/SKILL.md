---
name: feedback-runops
description: Send feedback (bug report, feature request, improvement suggestion) to the runops upstream repository. Without arguments, list feedback candidates found during the session. With arguments, file a specific issue.
---

# runops へフィードバックを送る

`{{ skill_prefix }}feedback-runops` は runops 本体への **バグ報告・機能要望・改善提案** を
GitHub issue として起票するスキル。現在の作業を止めずにサイドチャネルとして
フィードバックを送れる。

`tools/runops` に local patch がある場合も、この skill を使ってよい。
特に、汎用価値はありそうだが設計がまだ粗い、一部だけ汎用、draft PR には早い、
という場合は PR ではなく issue で upstream design discussion に回す。

## 引数なしの場合: フィードバック候補をリストアップ

引数なしで `{{ skill_prefix }}feedback-runops` を呼んだ場合、**今のセッション中に気づいた
フィードバック候補** を洗い出して一覧表示する。

以下の観点で候補を探す:

- セッション中にエラー・warning が出た runops コマンド
- workaround が必要だった箇所
- ドキュメントやヘルプが不足していると感じた場面
- 「こうなっていれば便利だった」と思った機能
- `tools/runops/` のコードを読んで気づいたバグ・改善点
- `tools/runops` local patch のうち、設計議論が必要な upstream 候補

出力フォーマット:

```
## フィードバック候補

1. [bug] `runo runs sync` — <具体的な問題>
2. [feature] `runo runs submit` — <欲しい機能>
3. [improvement] `update-harness` — <改善提案>

→ 起票するものがあれば `{{ skill_prefix }}feedback-runops <番号 or 内容>` で issue 化できます
```

候補がなければ「現時点でフィードバック候補はありません」と報告する。

---

## 引数ありの場合: issue を起票する

### 1. フィードバック内容を整理する

ユーザーの入力 (引数テキスト) または Agent が発見した問題から、
以下を整理する:

- **種別**: bug / feature / improvement / docs
- **要約**: 1 行のタイトル
- **詳細**: 概要・再現手順・期待する挙動
- **local patch がある場合**: branch / commit / current project で効いたこと /
  upstreamable parts / project-specific parts

### 2. 重複 issue を確認する

```bash
gh issue list --repo Nkzono99/runops --search "<キーワード>" --state all --limit 10
```

類似の既存 issue があれば、ユーザーに知らせて重複を避ける。

### 3. 環境情報を自動収集する

```bash
runo --version 2>/dev/null || echo "unknown"
python3 --version
uname -srm
```

### 4. ユーザーに確認する

起票する issue の内容 (タイトル + 本文) を **必ずユーザーに表示し、
確認を得てから** 起票する。勝手に issue を投げない。

### 5. issue を作成する

```bash
gh issue create \
  --repo Nkzono99/runops \
  --title "<タイトル>" \
  --body "$(cat <<'EOF'
## 概要
<何が問題か / どんな改善を提案するか>

## 再現手順 (bug の場合)
1. ...
2. ...

## 期待する挙動
<どうあるべきか>

## 補足
<ログ抜粋, 関連情報, 既に試した workaround など>

## Local patch / workaround (該当する場合)
- branch:
- commit:
- current project check:
- upstreamable parts:
- project-specific parts to exclude:
- open design questions:

## 環境
- runops version: <収集した情報>
- OS: <収集した情報>
- Python: <収集した情報>
EOF
)"
```

### 6. lab notebook に記録する

作成した issue の URL を lab notebook に追記する:

```bash
runo notes append "upstream feedback" "Filed <issue-url>: <タイトル>"
```

## 注意事項

- **ユーザー確認なしに issue を投げない** — 必ず内容を見せて OK をもらう
- プロジェクト固有の private 情報 (実データパス, クラスタ固有の秘密) を
  issue 本文に含めない
- project 固有の generated harness や研究状態を、そのまま upstream issue / PR
  に貼らない。汎用化できる source template / command / docs の話に分解する
- 同じ内容の重複 issue を切らない
- フィードバックを理由に **現在の研究タスクを止めない** — workaround で
  作業を進めつつ、サイドチャネルとして issue を投げる
