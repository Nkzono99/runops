---
name: setup-runops
description: Interactively prepare a runops project after runo init or runo setup. Use when the user has a generated runops project and wants help gathering research/case/survey requirements, checking doctor/context, deciding next steps, or following direct first-workflow setup instructions.
---

# runo init 後の project を立ち上げる

`runo init` または `runo setup` が済んだ project の最初の案内役。
ユーザーから研究・case・survey に必要な情報を聞き出し、直接指示が十分なら
そのまま初期整備を進め、完了後に次の使い方へ誘導する。

この skill は **bootstrap command そのものを説明する入口ではなく、生成済み
harness を使い始める入口**として扱う。まだ `runops.toml` がない場合だけ、
例外的に `{{ skill_prefix }}setup-env` や `runo init` / `runo setup` へ誘導する。

## 基本姿勢

- まず `runo init` 済みの local context を読む。ユーザーに聞くのは、ローカルから判定できない
  blocker だけにする。
- 直接指示が十分なら、追加質問で止めずに実行する。
- 研究内容が曖昧なら、質問はまとめて短く出す。仮置きできる項目は仮定して進める。
- 初期セットアップでは job submit しない。submit は survey / run のレビュー後に確認を挟む。
- `manifest.toml`, `input/`, `submit/job.sh`, `SITE.md` など runops 管理生成物を
  直接編集しない。

## まず確認すること

```bash
pwd
ls
```

project root にいるか、または親 directory に `runops.toml` があるか確認する。
通常は init 済みなので、次を実行して現状を把握する:

```bash
runo context --no-json
runo doctor
```

`runo` がまだ使えない、`.venv/` がない、`runops.toml` が見つからない場合は
初期化が未完了と判断し、`{{ skill_prefix }}setup-env` の内容に従って環境を修復する。

## 聞き出す項目

不足しているものだけ質問する。全部を一度に埋めようとしなくてよい。

| 項目 | 例 |
|---|---|
| init 後の確認 | project root、doctor の未解決項目 |
| simulator | `runo init` で選んだ simulator、追加したい simulator |
| site / launcher | Slurm site、partition、launcher (`srun`, `mpirun` など)、未設定なら候補 |
| 研究目的 | 何を調べたいか、仮説、観測量 |
| base input | 既存 case、入力ファイル、cookbook 起点、未定 |
| 最初の到達点 | campaign だけ / case まで / survey 雛形まで / run 生成まで |
| 資源・安全条件 | すぐ submit しない、small smoke から、walltime 上限など |

聞き方の例:

```text
runo init 後の初期整備に必要な確認だけします。
1. doctor で未解決の項目はありますか？ こちらでも確認します。
2. 最初の研究テーマ、base input、主に振りたいパラメータは決まっていますか？
3. まず campaign / case / survey / run 生成のどこまで進めたいですか？
```

## 直接指示がある場合

ユーザーが十分に具体的に指示したら、その指示を優先して進める。

例:

```text
init 済みの emses project で、flat_surface の campaign と survey 雛形まで作って。
submit はまだしない。
```

この場合:

1. `runo context --no-json` と `runo doctor` で init 済み project の状態を確認する
2. simulator / site / launcher の不足があれば修復方針を出す
3. `{{ skill_prefix }}setup-campaign` / `{{ skill_prefix }}new-case` /
   `{{ skill_prefix }}survey-design` を必要に応じて使う
4. submit はしない

## 初期化が未完了だった場合

この skill は init 後を主対象にする。ただし、`runops.toml` がない、`.venv/` がない、
`runo` が見つからないなど明らかに bootstrap が未完了なら、短く状況を説明して
次の経路に切り替える。

### 新規 project をまだ作っていない場合

```bash
uvx --from runops runo init
source .venv/bin/activate
runo doctor
```

simulator が明示されている場合は `runo init <SIM>` を使ってよい。非対話で
進めてよいことが明確なら `-y` を付ける。

### 既存 project をまだ setup していない場合

```bash
uvx --from runops runo setup <URL>
cd <project>
source .venv/bin/activate
runo doctor
```

bootstrap が終わったら、この skill の主経路に戻り、`runo doctor` と
`runo context --no-json` から初期整備を続ける。

## セットアップ後に行うこと

init 済み project が使える状態になったら、次の順で利用者を誘導する。

1. 現在の状態を短く要約する: project root、simulator、doctor 結果、未設定項目
2. 研究テーマがあるなら `{{ skill_prefix }}setup-campaign` で `campaign.toml` を整える
3. base input があるなら `{{ skill_prefix }}new-case` で case を作る
4. independent variables が見えているなら `{{ skill_prefix }}survey-design` で survey を作る
5. run 生成や submit は、対象・資源・確認条件を示してから進める
6. runops 自体の不満点や改善案が出たら、`{{ skill_prefix }}feedback-runops`
   で候補一覧、`{{ skill_prefix }}feedback-runops 不満点・改善案` で
   HarnessOps record と issue 下書きを作る

最後に、利用者が次に頼みやすい形で 2-4 個の依頼例を出す:

```text
次はこの順で進めるとよいです。
- campaign.toml を研究テーマから整理して。
- この入力ファイルをベースに case を作って。
- 照射角を振る survey.toml を作って。submit はまだしない。
- {{ skill_prefix }}feedback-runops setup 中に気になった改善点
```

## note に残すこと

project が初期化済みで `runo notes append` が使えるなら、準備段階の判断を
`{{ skill_prefix }}note` で残す。

- project を新規作成 / setup した理由
- 採用 simulator / site / launcher
- base input を採用した理由、または未定にした理由
- submit を保留した理由や smoke run 方針

## 完了条件

- `runo doctor` の結果を確認した
- project root と次に編集すべきファイルが明確
- campaign / case / survey / run 生成のどこまで進めたかを説明した
- 次にユーザーが頼むべき具体的な依頼例を提示した
