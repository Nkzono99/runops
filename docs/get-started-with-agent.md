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
project / simulator / site に外部 Codex plugin 推薦がある場合、`runo init` と
生成される `AGENTS.md` / `CLAUDE.md` に推奨 plugin と導入手順が表示されます。
たとえば `emses` では MPIEMSES3D / emout の plugin、`camphor` site profile では
KUDPC HPC plugin、`beach` では BEACH Context plugin が案内されます。
既存 project では `runo setup` の出力と `runo update-harness` が
`[project.codex_plugins]` も含めた同じ推薦 inventory を使うため、project 固有の
解析 workflow や handoff plugin も生成 harness に反映できます。
runops は plugin を自動 install せず、
ユーザーの Codex 環境で `/plugins` や `codex plugin ...` により有効化します。
生成済み project では、Codex なら `$setup-plugins`、Claude Code なら
`/setup-plugins` を使うと、Agent が `install_hint` / `activation_hint` を読み、
可能な範囲で install / enable / plugin-provided hook 導線を整えます。
既存 project で推薦を確認したい場合は `runo plugins`、agent や外部 tool から
読む場合は `runo plugins --json` を使います。`runo plugins --check` は推薦
メタデータの欠落を検査しますが、user-local な plugin install 状態は検査しません。

ベース入力ファイル (`plasma.toml`, `beach.toml` など) を明示すると意図が伝わりやすくなります。
一方で、まだベースを決めていない場合でも、Agent は `runo plugins --json` の
`delegated_capabilities` から simulator/environment plugin を確認し、
`.runops/knowledge/enabled/imports.md`、`materials/` を読んで case の叩き台を作れます。
任意の `refs/` mirror にある docs/cookbook は、plugin や明示的 knowledge source が
使えない場合の fallback として参照します。

あとはエージェントが campaign 設計、case 作成、survey 展開、run 生成・投入・解析・知見整理を進めます。
人間が CLI の全体を覚える必要はありません。

## プロジェクトを用意する

新規作成の場合:

```bash
uvx --from runops runo init
uvx --from runops runo doctor
uvx --from runops runo plugins --check
# Codex: $setup-plugins
# Claude Code: /setup-plugins
```

既存プロジェクトをセットアップする場合:

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
cd my-project
uvx --from runops runo doctor
uvx --from runops runo plugins --check
# Codex: $setup-plugins
# Claude Code: /setup-plugins
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

`setup-plugins` は推奨 plugin と plugin-provided hook 導線を整えるための任意ステップです。
plugin が整ったら、次に `setup-runops` で project の聞き取りへ進みます。

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
| 投入だけ行う | `この3 runを投入して。job_idを報告したら、待機やlog確認はせず返して。` |
| 初動だけ確認する | `投入後、正常に動いているか数step見て。10分以内で確認できたところまで報告して。` |
| 失敗 run を診断する | `failed run を確認して。log を読んで failure_reason を整理し、retry 方針を提案して。` |
| 解析・知見を整理する | `completed run を summarize / collect して、insight と fact の候補を分けてまとめて。` |
| runops にフィードバックする | project 固有情報を除いた再現手順と issue 下書きを作るよう依頼する |

ポイントは、run の入力を場当たり的に直すのではなく、再利用すべき変更を `campaign.toml` → `case.toml` → `survey.toml` に戻すよう依頼することです。

submit の既定動作は job_id の報告までです。投入後の待機、`sync`、log/step 確認は
自動では始まりません。初動確認が必要なときだけ、確認条件と期限を依頼に含めてください。

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

## runops へのフィードバック

不満点や bug 候補は `runo research append` で project 内に短く記録できます。
upstream issue を作る場合は、再現手順、期待/実際の挙動、workaround を下書きし、
private path、クラスタ固有情報、未公開 result を除いたことを人が確認してから起票します。

## 次に読む

- [README.md](../README.md) — 生成される構造と全体像
- [layers/README.md](layers/README.md) — interface / experiment / execution / analysis / research / knowledge / harness / upstream の責務分離
- [layers/interface.md](layers/interface.md) — CLI / action surface / human gate の境界
- [agent-user-guide.md](agent-user-guide.md) — Agent が守る基本ルール
- [toml-reference.md](toml-reference.md) — TOML フィールドを手で確認したいとき
