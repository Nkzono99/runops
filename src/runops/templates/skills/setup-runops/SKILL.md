---
name: setup-runops
description: Interactively prepare a runops project after runo init or runo setup. Use when the user has a generated runops project and wants help gathering research/case/survey requirements, checking doctor/context, deciding next steps, or following direct first-workflow setup instructions.
---

# 生成済み runops project を使い始める

`runo init` / `runo setup` / `runo update-harness` で配布された project harness の
最初の案内役。
ユーザーから研究・case・survey に必要な情報を聞き出し、直接指示が十分なら
そのまま初期整備を進め、完了後に次の使い方へ誘導する。

この skill が見えている時点では、基本的に project は生成済みとみなす。
bootstrap が済んだかを確認することを主目的にしない。

この skill の主成果は、`uvx --from runops runo context` や
`uvx --from runops runo doctor` の確認そのものではなく、
**生成済み project の現在状態を読み、利用者が次に進められる形へ案内すること**。
致命的な blocker がなければ、状態確認だけで応答を終えない。
必ず「セットアップ後に行うこと」に進み、状態要約、次アクション、
頼みやすい依頼例を提示する。

この skill は **bootstrap command そのものを説明する入口ではなく、生成済み
harness を使い始める入口**として扱う。`runops.toml` が見つからない場合は、
まず cwd のずれや project root の取り違えを疑う。実際に環境が壊れている場合だけ、
例外的に `{{ skill_prefix }}setup-env` や `runo init` / `runo setup` へ誘導する。

## 基本姿勢

- まず生成済み project の local context を読む。ユーザーに聞くのは、ローカルから判定できない
  blocker だけにする。
- `doctor` の未解決項目は、利用者に先に聞かず agent が確認する。blocker があれば
  こちらから短く共有し、修復方針を示す。
- `uvx --from runops runo context` / `uvx --from runops runo doctor` の確認だけで応答を終えない。致命的な blocker が
  なければ、必ず次に進むための案内まで出す。
- `pwd` / `ls` は「init 成功判定」ではなく、今どの project を見ているかの確認として使う。
- 直接指示が十分なら、追加質問で止めずに実行する。
- 研究内容が曖昧なら、質問はまとめて短く出す。仮置きできる項目は仮定して進める。
- 初期セットアップでは job submit しない。submit は survey / run のレビュー後に確認を挟む。
- `manifest.toml`, `input/`, `submit/job.sh`, `SITE.md` など runops 管理生成物を
  直接編集しない。

## まず確認すること

この節は bootstrap 完了判定ではない。現在の project root、simulator、site / launcher、
doctor の未解決項目を把握して、次の案内へ進むために行う。

```bash
pwd
ls
```

project root にいるか、または親 directory に `runops.toml` があるかを見て、
次を実行して現状を把握する:

```bash
uvx --from runops runo context --no-json
uvx --from runops runo doctor
uvx --from runops runo plugins --check
```

`runops.toml` が見つからない場合は、まず cwd が project root から外れていないか確認する。
`uvx` が使えない、`.venv/` が壊れているなど実行環境の問題なら、短く状況を説明して
`{{ skill_prefix }}setup-env` の内容に従って環境を修復する。
それ以外は、確認結果を判断材料として使い、次の「セットアップ後に行うこと」へ進む。

## 聞き出す項目

不足しているものだけ質問する。全部を一度に埋めようとしなくてよい。

| 項目 | 例 |
|---|---|
| project 状態 | project root、doctor の未解決項目、simulator / site / launcher |
| simulator | `runo init` で選んだ simulator、追加したい simulator |
| site / launcher | Slurm site、partition、launcher (`srun`, `mpirun` など)、未設定なら候補 |
| 研究目的 | 何を調べたいか、仮説、観測量 |
| base input | 既存 case、入力ファイル、cookbook 起点、未定 |
| 最初の到達点 | campaign だけ / case まで / survey 雛形まで / run 生成まで |
| 資源・安全条件 | すぐ submit しない、small smoke から、walltime 上限など |

聞き方の例:

```text
project の状態はこちらで確認します。次に進めるための設計情報だけ教えてください。
1. 最初の研究テーマ、base input、主に振りたいパラメータは決まっていますか？
2. site / launcher / 資源条件で、研究上の制約や希望はありますか？
3. まず campaign / case / survey / run 生成のどこまで進めたいですか？
```

## 直接指示がある場合

ユーザーが十分に具体的に指示したら、その指示を優先して進める。

例:

```text
emses project で、flat_surface の campaign と survey 雛形まで作って。
submit はまだしない。
```

この場合:

1. `uvx --from runops runo context --no-json` と
   `uvx --from runops runo doctor`、`uvx --from runops runo plugins --check`
   で project の現在状態を読む
2. simulator / site / launcher の不足があれば修復方針を出す
3. `{{ skill_prefix }}setup-campaign` / `{{ skill_prefix }}new-case` /
   `{{ skill_prefix }}survey-design` を必要に応じて使う
4. submit はしない

## project として動かない場合

この skill は配布済み project を前提にする。`runops.toml` がない場合は、まず
project root から外れていないか確認する。`.venv/` がない、`runo` が見つからないなど
明らかに実行環境が壊れている場合だけ、短く状況を説明して次の経路に切り替える。

### project root から外れていた場合

```bash
cd <project>
uvx --from runops runo context --no-json
uvx --from runops runo doctor
```

### harness や環境が壊れていた場合

`{{ skill_prefix }}setup-env` で環境を修復する。必要なら次も使う:

```bash
uvx --from runops runo doctor
uvx --from runops runo update-harness --plan
uvx --from runops runo update-harness --apply-chain
```

### 新規作成 / clone から必要な場合

利用者がまだ project を作っていない、または別 project を clone したいと言っている場合だけ、
次の経路に切り替える:

```bash
# 新規 project
uvx --from runops runo init

# 既存 project
uvx --from runops runo setup <URL>
```

bootstrap が終わったら、この skill の主経路に戻り、project の現在状態を読んで
初期整備を続ける。

## セットアップ後に行うこと

ここがこの skill の主経路。project が使える状態だと分かったら、
この節を省略せず、次の順で利用者を誘導する。

1. 現在の状態を短く要約する: project root、simulator、doctor 結果、未設定項目
2. init / setup で生成された scaffold が未 commit なら、研究作業に入る前に
   baseline commit を提案する
3. 研究テーマがあるなら `{{ skill_prefix }}setup-campaign` で `campaign.toml` を整える
4. base input があるなら `{{ skill_prefix }}new-case` で case を作る
5. independent variables が見えているなら `{{ skill_prefix }}survey-design` で survey を作る
6. run 生成や submit は、対象・資源・確認条件を示してから進める
7. runops 自体の不満点や改善案が出たら、`{{ skill_prefix }}feedback-runops`
   で候補一覧、`{{ skill_prefix }}feedback-runops 不満点・改善案` で
   HarnessOps record と issue 下書きを作る

baseline commit は、生成直後の project scaffold とその後の研究作業を diff で分けるための
目印として使う。`git status --short` で生成物が未 commit なら、次のような commit を提案する。
ただし、ユーザーが明示的に頼んだ場合だけ `git add` / `git commit` する。

```bash
git status --short
git add .
git commit -m "chore: scaffold runops project"
```

最後に、利用者が次に頼みやすい形で 2-4 個の依頼例を出す:

```text
次はこの順で進めるとよいです。
- campaign.toml を研究テーマから整理して。
- この入力ファイルをベースに case を作って。
- 照射角を振る survey.toml を作って。submit はまだしない。
- {{ skill_prefix }}feedback-runops setup 中に気になった改善点
```

## note に残すこと

project で `runo notes append` が使えるなら、準備段階の判断を
`{{ skill_prefix }}note` で残す。

- project を新規作成 / setup した理由
- 採用 simulator / site / launcher
- base input を採用した理由、または未定にした理由
- submit を保留した理由や smoke run 方針

## 完了条件

- `runo doctor` と `runo plugins --check` の結果を確認した
- project root と次に編集すべきファイルが明確
- campaign / case / survey / run 生成のどこまで進めたかを説明した
- init / setup 生成物の baseline commit が必要かどうかを案内した
- project が使える状態なら、状態確認だけで応答を終えず、次アクションへ誘導した
- 次にユーザーが頼むべき具体的な依頼例を提示した
