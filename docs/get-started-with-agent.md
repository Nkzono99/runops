# AI エージェントではじめる runops

AI エージェントと一緒にシミュレーションプロジェクトを立ち上げるためのガイドです。
TOML ファイルを最初から手で書く必要はありません。研究内容をエージェントに伝えれば、campaign・case・survey の設計から run 管理まで支援してもらえます。

このガイドの前提は、**人間が runops CLI を順番に叩いて研究を進めるのではない**
ということです。CLI は Agent と harness が安全に project state を操作するための
interface です。人間は研究意図、制約、確認、解釈に集中します。

## あなたが用意するもの

エージェントに渡す前に、主に次の 2 点を決めておいてください。

1. **研究の方向性** — テーマ、仮説、探索したい変数、注目する観測量
2. **ベース入力の方針** — 既存の入力テンプレート、plugin/knowledge source、手元の資料のどれを起点に組み立てるか

`runo init` では通常、simulator や launcher の設定を対話的に選ぶため、最初の依頼でそれらを毎回書き直す必要はありません。

ベース入力ファイル (`plasma.toml`, `beach.toml` など) を明示すると意図が伝わりやすくなります。
一方で、まだベースを決めていない場合でも、Agent は simulator/environment plugin、
`.runops/knowledge/enabled/imports.md`、`materials/`、任意の `refs/` mirror にある
docs/cookbook を順に確認し、入力例や推奨パラメータをもとに case の叩き台を作れます。

あとはエージェントが campaign 設計、case 作成、survey 展開、run 生成・投入・解析・知見整理を進めます。
人間が CLI の全体を覚える必要はありません。

## プロジェクトを用意する

新規作成の場合:

```bash
uvx --from runops runo init
uvx --from runops runo doctor
```

既存プロジェクトをセットアップする場合:

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
cd my-project
uvx --from runops runo doctor
```

`runo init` がディレクトリ構造と初期ファイルを作ります。
この bootstrap だけは人間が直接実行して構いません。その後は CLI を順番に叩くより、
すぐにエージェントへ研究内容を渡して構成を整えてもらう方が早いです。
あわせて Claude Code 向けのガードも生成され、`manifest.toml`、`input/`、`submit/job.sh`、
`SITE.md` などの生成物は直接編集しない前提になります。

運用全体を俯瞰したい場合は [layers/README.md](layers/README.md) を先に見ると、
Experiment Layer の `campaign.toml`・`case.toml`・`survey.toml` と、
Execution Kernel の `manifest.toml` がそれぞれ何の役割を持つか掴みやすくなります。

## 最初の依頼の出し方

`setup-runops` は、**`runo init` / `runo setup` が終わった後**に使う
開始時の聞き取り用 SKILL です。最初のプロンプトでは、細かい TOML や CLI
コマンドを書かずに、生成済み project の中でこれだけ入力してください。

Codex の場合:

```text
$setup-runops
```

Claude Code の場合は `/setup-runops` と入力します。

Agent が `runo doctor` や project context を確認し、セットアップに必要なことを
順番に聞きます。研究テーマ、使いたい simulator、base input、最初にどこまで
進めたいかなど、聞かれたことに答えていけば十分です。情報が揃ったら、
campaign / case / survey / run 生成のどこまで進めるべきかを Agent が案内します。

初回はそれ以上のプロンプトを用意する必要はありません。以後は Agent の質問に
答えていく形で進めます。

<details>
<summary>最初からまとめて指示したい場合</summary>

Agent との聞き取りを短くしたい場合は、研究目的と制約をまとめて直接伝えても
構いません。その場合も、CLI コマンドを列挙するより、研究内容・base input・
最初の到達点を書きます。

```text
このプロジェクトでは、月面平面に太陽風プラズマが入射し、
光電子放出があるときの表面帯電を調べたい。
ベース入力テンプレートは cases/emses/flat_surface/plasma.toml を使いたい。
照射角を主な独立変数として調べたい。

まず project を確認して、plan を示したうえで campaign.toml と case 定義を整えて。
必要なら survey の雛形まで作って。submit はまだしないで。
```

ベース入力が未定なら、次のように頼めます。

```text
このプロジェクトでは、月面平面に太陽風プラズマが入射し、
光電子放出があるときの表面帯電を調べたい。どのようなパラメータを用いるべきか。
照射角を主な独立変数として調べたい。

まず project を確認して、plan を示したうえで campaign.toml と case 定義を整えて。
必要なら survey の雛形まで作って。submit はまだしないで。
```

</details>

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
| runops にフィードバックする | `$feedback-runops` (`/feedback-runops`) で候補一覧、`$feedback-runops 不満点・改善案` で HarnessOps record と issue 下書きを作成 |

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
- **破壊的な操作** — `cancel`、`archive`、`purge-work`、`delete`
- **研究の意味が変わる操作** — 仮説の方向性が変わる `campaign.toml` の編集

それ以外はエージェントに任せて大丈夫です。

## runops へのフィードバックを HarnessOps 経由で issue 下書きにする

プロジェクトを運用していて runops 本体への不満点・改善点・バグらしき挙動に
気づいたら、その場でエージェントに feedback 記録を頼んでください。runops が生成する
プロジェクト側ハーネスには `feedback-runops` SKILL が含まれており、現在の研究タスクを
止めずに HarnessOps の `harness-feedback/` へ記録し、サニタイズ済み bundle から
upstream issue 下書きへ進められます。

候補を見たいだけなら、引数なしで呼びます。Codex では:

```text
$feedback-runops
```

Claude Code では:

```text
/feedback-runops
```

具体的な不満点や改善案がある場合は、続けて本文を書きます。Codex では:

```text
$feedback-runops runo runs submit の挙動がわかりにくかったので、改善してほしい
```

Claude Code では:

```text
/feedback-runops runo runs submit の挙動がわかりにくかったので、改善してほしい
```

引数なしなら、そのセッション中に見つかった候補を一覧します。具体的な内容を
渡すと、`hops add-failure` / `hops route` / `hops add-feedback` /
`hops feedback export --sanitize --format github-issue` で record と下書きを作り、
重複 issue を確認し、環境情報を集め、issue のタイトルと本文案を作ります。

この SKILL は安全のため、ユーザー確認なしに GitHub issue を作りません。
起票前に必ず内容を表示させ、private なデータパス・クラスタ固有の秘密・未公開の
研究情報が本文に入っていないことを確認してください。作成後は issue URL を
`notes/YYYY-MM-DD.md` に記録しておくと、後で「あのときの改善要望」を辿りやすくなります。

`hops` CLI が利用できる環境では、`runo init` / `runo setup` が
`hops init --profile runops-project` を連鎖して呼び、`runo update-harness` が
`hops update-harness` を連鎖して呼びます。HarnessOps を使わない環境では
`--no-harnessops` でこの連携を無効化できます。

## 次に読む

- [README.md](../README.md) — 生成される構造と全体像
- [layers/README.md](layers/README.md) — interface / experiment / execution / analysis / research / knowledge / harness / upstream の責務分離
- [layers/interface.md](layers/interface.md) — CLI / action surface / human gate の境界
- [agent-user-guide.md](agent-user-guide.md) — Agent が守る基本ルール
- [toml-reference.md](toml-reference.md) — TOML フィールドを手で確認したいとき
