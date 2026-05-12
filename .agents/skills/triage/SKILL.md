---
name: triage
description: "Triage open GitHub issues: review new issues, assess priority, filter spam/malicious content, suggest which to tackle, and close resolved or invalid issues."
---

# Issue トリアージ

`$triage` は runops リポジトリの GitHub issue を一括レビューし、
対応方針を提案するスキル。GitHub issue の取得・close などのリモート操作は
`gh` に任せるが、継続的に扱う改善候補は HarnessOps の `harness-lab/` に
import し、評価ケース・仮説・判断へ進める。

## 事前確認

```bash
hops doctor --check-overlay --check-records
hops migrate --check
```

`hops` が使えない場合は、GitHub issue の読み取りだけ行い、HarnessOps import は
未実施として報告する。`.harnessops/` や `harness-lab/records/` を手で編集しない。

## 手順

### 1. Open issue を一覧取得

```bash
gh issue list --state open --limit 30
```

### 2. 各 issue を評価

issue ごとに以下の観点で評価する:

| 観点 | 判定 |
|------|------|
| **正当性** | 悪意・スパム・無関係な内容でないか |
| **再現性** | バグなら再現手順があるか、実際にコードベースで確認できるか |
| **影響度** | 影響を受けるユーザー・ワークフローの範囲 |
| **難易度** | 修正の複雑さ (軽微 / 中 / 大) |
| **重複** | 既存の issue や実装済み機能と重複していないか |

### 3. HarnessOps に import する

正当な改善候補、設計議論、再発しそうなハーネス摩擦は、GitHub issue を入力として
`harness-lab/` に取り込む:

```bash
hops feedback import --issue <NUMBER> --repo Nkzono99/runops
```

import された `FB` レコードのうち、実装候補として扱うものは評価ケース化する:

```bash
hops lab new-eval-case --from FB0001
hops propose --from E0001
```

`hops feedback import --issue` が取り込む本文が不足する場合は、`gh issue view` で
本文・コメント・ラベルを読み、トリアージ報告に補足する。未サニタイズ情報を
issue コメントや公開文書へ戻さない。

### 4. 悪意ある issue のフィルタリング

以下に該当する issue は close を提案する:

- スパム (無関係な宣伝、bot 投稿)
- 悪意のあるコード・リンクを含む
- プロジェクトと無関係な内容
- 個人攻撃・ハラスメント

```bash
gh issue close <NUMBER> --comment "Closed: <理由>"
```

### 5. 優先度付けと対応方針の提案

ユーザーに以下の形式で報告する:

```
## トリアージ結果

### 対応推奨 (高)
- #N: <タイトル> — <理由・工数見積> / HarnessOps: <FB/E/H id or 未import>

### 対応推奨 (中)
- #N: <タイトル> — <理由・工数見積> / HarnessOps: <FB/E/H id or 未import>

### 保留 / 要議論
- #N: <タイトル> — <保留理由>

### Close 推奨
- #N: <タイトル> — <close 理由>
```

### 6. ユーザー判断を仰ぐ

トリアージ結果を提示した後、ユーザーに以下を確認する:

- どの issue に取り掛かるか
- close してよい issue はどれか
- 追加情報が必要な issue はあるか

## 対応完了時の処理

issue に対応した後は以下の手順で close する:

### コミットでの紐づけ

commit message に `Closes #N` を含めると、push 時に自動 close される:

```
feat: add --qos option to runs submit

Closes #15
```

### 手動 close

push 前に close する場合や、コミットに紐づけない場合:

```bash
gh issue close <NUMBER> --comment "Fixed in <commit-hash> — <概要>"
```

### 対応しないと決めた issue

理由を明記して close する:

```bash
gh issue close <NUMBER> --comment "Won't fix: <理由>"
```

## 注意事項

- ユーザーの確認なしに issue を close しない (スパム除く)
- close 時は必ずコメントで理由を残す
- 対応済み issue は対応コミットのハッシュを記載する
- `harness-lab/records/` は `hops` 以外で直接書き換えない
- 採用判断は評価ケース、証拠、回帰リスク、ガードパスが揃ってから作る
