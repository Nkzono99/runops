# AI エージェントではじめる runops

AI エージェントと一緒にシミュレーションプロジェクトを立ち上げるためのガイドです。
TOML ファイルを最初から手で書く必要はありません。研究内容をエージェントに伝えれば、campaign・case・survey の設計から run 管理まで支援してもらえます。

## あなたが用意するもの

エージェントに渡す前に、主に次の 2 点を決めておいてください。

1. **研究の方向性** — テーマ、仮説、探索したい変数、注目する観測量
2. **ベース入力の方針** — 既存の入力テンプレートを使うか、simulator repo の `cookbook/` を起点に組み立てるか

`runops init` では通常、simulator や launcher の設定を対話的に選ぶため、最初の依頼でそれらを毎回書き直す必要はありません。

ベース入力ファイル (`plasma.toml`, `beach.toml` など) を明示すると意図が伝わりやすくなります。
一方で、まだベースを決めていない場合でも、Agent は `refs/` 以下の simulator docs や `cookbook/` を探索して、入力例や推奨パラメータをもとに case の叩き台を作れます。

あとはエージェントが campaign 設計、case 作成、survey 展開、run 生成・投入・解析・知見整理を進めます。

## プロジェクトを用意する

新規作成の場合:

```bash
uvx --from runops runops init
source .venv/bin/activate
runops doctor
```

既存プロジェクトをセットアップする場合:

```bash
uvx --from runops runops setup https://github.com/user/my-project.git
cd my-project
source .venv/bin/activate
runops doctor
```

`runops init` がディレクトリ構造と初期ファイルを作ります（詳細は [README.md](../README.md) を参照）。
初期セットアップを細かく確認するより、すぐにエージェントへ研究内容を渡して構成を整えてもらう方が早いです。
あわせて Claude Code 向けのガードも生成され、`manifest.toml`、`input/`、`submit/job.sh`、
`SITE.md` などの生成物は直接編集しない前提になります。

運用全体を俯瞰したい場合は [AI Agent 運用概念図](project-flow.md) を先に見ると、
`campaign.toml`・`case.toml`・`survey.toml`・`manifest.toml` がそれぞれ何の役割を持つか掴みやすくなります。

## 最初の依頼の出し方

何を調べたいかと、ベース入力をどうしたいかをまとめて伝えるのが効果的です。

```text
このプロジェクトでは、月面平面に太陽風プラズマが入射し、
光電子放出があるときの表面帯電を調べたい。
ベース入力テンプレートは cases/emses/flat_surface/plasma.toml を使いたい。
照射角を主な独立変数として調べたい。

まず project を確認して、plan を示したうえで campaign.toml と case 定義を整えて。
必要なら survey の雛形まで作って。
```

ベース入力が未定なら、次のように頼めます。

```text
このプロジェクトでは、月面平面に太陽風プラズマが入射し、
光電子放出があるときの表面帯電を調べたい。どのようなパラメータを用いるべきか。
照射角を主な独立変数として調べたい。

まず project を確認して、plan を示したうえで campaign.toml と case 定義を整えて。
必要なら survey の雛形まで作って。
```

SKILL 名を明示する必要はありません。依頼内容に応じて必要な SKILL は自動選択されます。

## よくある依頼パターン

細かい TOML 構文を知らなくても、やりたいことをそのまま伝えれば動きます。

| やりたいこと | 依頼の例 |
|---|---|
| 研究意図を整理する | `campaign.toml を整えて。仮説、独立変数、観測量がわかる形にして。` |
| case を作る | `このテンプレートをベースに case を作って。共通 job 設定と params は case に寄せて。` |
| survey を作る | `campaign の independent variables をもとに survey.toml を作って。命名規則も入れて。` |
| run を展開する | `この survey から run を生成して。created 状態まで進めて。` |
| 投入前にレビューする | `submit 前に plan と対象 run を確認して。初回 bulk submit なので確認を挟んで。` |
| 失敗 run を診断する | `failed run を確認して。log を読んで failure_reason を整理し、retry 方針を提案して。` |
| 解析・知見を整理する | `completed run を summarize / collect して、insight と fact の候補を分けてまとめて。` |

ポイントは、run の入力を場当たり的に直すのではなく、再利用すべき変更を `campaign.toml` → `case.toml` → `survey.toml` に戻すよう依頼することです。

## SKILL を明示するとき

通常は「何をしてほしいか」を書けば十分です。意図がずれるときだけ、ひと言添えてください。

```text
campaign 設計用の SKILL を使って campaign.toml を整理して。
```

```text
知見整理用の SKILL を使って、今回の結果を insight として保存して。
```

## 人間が確認を入れる場面

エージェント中心で進めても、以下の操作だけは確認を挟んでください。

- **コストが高い操作** — 新しい survey の初回 bulk submit、walltime / memory / node 数を増やす retry
- **破壊的な操作** — `archive`、`purge-work`
- **研究の意味が変わる操作** — 仮説の方向性が変わる `campaign.toml` の編集

それ以外はエージェントに任せて大丈夫です。

## runops へのフィードバックを issue にする

プロジェクトを運用していて runops 本体への不満点・改善点・バグらしき挙動に
気づいたら、その場でエージェントに issue 起票を頼んでください。runops が生成する
プロジェクト側ハーネスには `feedback-runops` SKILL が含まれており、現在の研究タスクを
止めずに upstream へフィードバックできます。

例えば次のように依頼できます。

```text
今の作業で runops への不満点や改善点があれば、feedback-runops SKILL を使って
issue 候補を整理して。起票する前にタイトルと本文を見せて確認して。
```

```text
runops runs submit の挙動がわかりにくかったので、改善要望として issue を作って。
再現手順、期待する挙動、今回の workaround も本文に入れて。
```

SKILL 名を直接指定する場合、Claude Code では `/feedback-runops`、Codex では
`$feedback-runops` のように呼びます。引数なしなら、そのセッション中に見つかった
候補を一覧します。具体的な内容を渡すと、重複 issue を確認し、環境情報を集め、
issue のタイトルと本文案を作ります。

この SKILL は安全のため、ユーザー確認なしに GitHub issue を作りません。
起票前に必ず内容を表示させ、private なデータパス・クラスタ固有の秘密・未公開の
研究情報が本文に入っていないことを確認してください。作成後は issue URL を
`notes/YYYY-MM-DD.md` に記録しておくと、後で「あのときの改善要望」を辿りやすくなります。

## 次に読む

- [README.md](../README.md) — 生成される構造と全体像
- [project-flow.md](project-flow.md) — `runops init` 後の project を Agent とどう運用するかの概念図
- [agent-user-guide.md](agent-user-guide.md) — Agent が守る基本ルール
- [toml-reference.md](toml-reference.md) — TOML フィールドを手で確認したいとき
