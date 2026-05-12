---
name: feedback-runops
description: Record runops feedback through HarnessOps, export a sanitized upstream bundle, and only then draft or file a GitHub issue with user confirmation.
---

# runops へフィードバックを送る

`{{ skill_prefix }}feedback-runops` は runops 本体への **バグ報告・機能要望・改善提案** を
HarnessOps に記録し、サニタイズ済み bundle を作ってから issue 下書きまたは起票へ進める
thin wrapper。records / routing / sanitize / export は必ず `hops` CLI に委譲する。

`tools/runops` に local patch がある場合も、この skill を使ってよい。
特に、汎用価値はありそうだが設計がまだ粗い、一部だけ汎用、draft PR には早い、
という場合は PR ではなく issue で upstream design discussion に回す。

## 事前確認

まず HarnessOps overlay があるか確認する:

```bash
hops doctor --check-overlay
```

`hops` が見つからない、または overlay が未初期化なら、次を実行する前にユーザーへ
「HarnessOps project overlay を作る」ことを説明する。runops project では通常:

```bash
hops detect
hops init --profile runops-project --with-agent-bridge
hops doctor --check-overlay --check-records
```

`hops init` が既存ファイルの上書きを拒否したら停止し、競合ファイルを報告する。
`.harnessops/`、`harness-feedback/` の構造を手で組み替えない。

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

→ 記録するものがあれば `{{ skill_prefix }}feedback-runops <番号 or 内容>` で HarnessOps 経由の issue 下書きにできます
```

候補がなければ「現時点でフィードバック候補はありません」と報告する。

---

## 引数ありの場合: HarnessOps に記録して export する

### 1. フィードバック内容を整理する

ユーザーの入力 (引数テキスト) または Agent が発見した問題から、
以下を整理する:

- **種別**: bug / feature / improvement / docs
- **要約**: 1 行のタイトル
- **詳細**: 概要・再現手順・期待する挙動
- **local patch がある場合**: branch / commit / current project で効いたこと /
  upstreamable parts / project-specific parts

プロジェクト固有の研究判断、実データパス、クラスタ固有の秘密、未公開語は
upstream feedback へ混ぜない。必要なら `.harnessops/sanitize.yml` を提案する。

### 2. 失敗レコードを作る

状態変更は `hops` に委譲する:

```bash
hops add-failure --title "<短い題名>" --target runops \
  --context "<文脈>" \
  --what-happened "<起きたこと>" \
  --why-matters "<重要性>" \
  --desired-behavior "<望ましい挙動>" \
  --local-workaround "<回避策>"
hops route --record F0001
```

`hops add-failure` が出力した実際の ID を使う。route 結果が
`target-upstream-candidate` でない場合は、なぜ issue にしないかを報告する。

### 3. upstream feedback 下書きを作って sanitize export する

```bash
hops add-feedback --from F0001 --target runops \
  --type "<bug|feature|improvement|docs>" \
  --title "<issue候補タイトル>" \
  --summary "<サニタイズ可能な要約>"
hops feedback export --target runops --sanitize --format github-issue
```

export された `harness-feedback/views/exported-feedback/UF*.md` を読み、
ローカル絶対パス、private terms、protected/private paths の内容が残っていないか確認する。

### 4. 重複 issue を確認する

```bash
gh issue list --repo Nkzono99/runops --search "<キーワード>" --state all --limit 10
```

類似の既存 issue があれば、ユーザーに知らせて重複を避ける。

### 5. 環境情報を自動収集する

```bash
runo --version 2>/dev/null || echo "unknown"
python3 --version
uname -srm
```

### 6. ユーザーに確認する

起票する issue の内容 (タイトル + サニタイズ済み本文) を **必ずユーザーに表示し、
確認を得てから** 起票する。勝手に issue を投げない。

### 7. issue を作成する

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

GitHub issue は共有チャンネルであり、HarnessOps の正本は `harness-feedback/` の
failure / upstream-feedback record と export bundle。issue 作成後も records を
手編集しない。

### 8. lab notebook に記録する

作成した issue の URL を lab notebook に追記する:

```bash
runo notes append "upstream feedback" "Filed <issue-url>: <タイトル>"
```

## 注意事項

- **ユーザー確認なしに issue を投げない** — 必ず内容を見せて OK をもらう
- 未サニタイズの feedback を issue / PR / 公開文書へ貼らない
- `harness-feedback/records/` 配下を手で作成・移動・書換えしない
- プロジェクト固有の private 情報 (実データパス, クラスタ固有の秘密) を
  issue 本文に含めない
- project 固有の generated harness や研究状態を、そのまま upstream issue / PR
  に貼らない。汎用化できる source template / command / docs の話に分解する
- 同じ内容の重複 issue を切らない
- フィードバックを理由に **現在の研究タスクを止めない** — workaround で
  作業を進めつつ、サイドチャネルとして issue を投げる
