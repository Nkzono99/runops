---
name: setup-runops
description: Use when a generated runops project needs orientation and progress toward its first campaign, case, survey, or created-run milestone.
---

# 生成済み project を最初の研究状態へ進める

## 実行契約

- **Goal**: 利用者が指定した最初の milestone まで project を進める
- **Done**: project health と現在状態が分かり、milestone の artifact と次の依頼候補を示せる
- **Budget**: context / doctor は各1回。plugin確認は Goal が推薦 capability に依存するとき1回
- **Default milestone**: campaign、case、survey、created run のうち依頼に最も近い段階

この skill は `runo init` / `runo setup` / `runo update-harness` 後の project を入口にする。
project は生成済みとみなし、診断結果を Goal への routing に使う。

## Entry routing

| 観測状態 | 次の経路 |
|---|---|
| `runops.toml` が現在または親 directory にある | project root で主経路へ進む |
| runtime / harness が blocker | `{{ skill_prefix }}setup-env` または `runo update-harness --plan` |
| project が未作成 | `runo init` |
| clone 元が指定済み | `runo setup <URL>` |

## 主経路

1. project root を確定する
2. 次を実行して context と blocker を得る

   ```bash
   uvx --from runops runo context --no-json
   uvx --from runops runo doctor
   ```

3. Goal が plugin capability に依存する場合は `runo plugins --json` と
   `{{ skill_prefix }}setup-plugins` で委譲先を確定する
4. local state から決まらない設計情報だけをまとめて聞く
5. milestone に対応する skill を実行する
6. Done の artifact、残った blocker、次に頼める依頼例を報告する

## 最小限の設計入力

| milestone | 必要な入力 | 委譲先 |
|---|---|---|
| campaign | 研究目的、仮説、観測量 | `{{ skill_prefix }}setup-campaign` |
| case | simulator、base input、固定 parameter | `{{ skill_prefix }}new-case` |
| survey | independent variables、範囲、点数、cost ceiling | `{{ skill_prefix }}survey-design` |
| created run | case / survey、生成先、件数 | `{{ skill_prefix }}create-run` |

site / launcher / 資源条件は該当 milestone の判断に使う。仮置き可能な値は仮定と根拠を示し、
研究の意味や計算規模を変える不足情報は質問する。

依頼例:

```text
emses project で、flat_surface の campaign と survey 雛形まで作って。
Done は survey の lint が通り、run 数と概算 core-hour が分かること。
```

## Baseline と研究記録

生成直後の scaffold が未 commit の場合は、研究差分の起点として baseline commit を提案する。
commit が Goal に含まれる場合は次を使う。

```bash
git status --short
git add .
git commit -m "chore: scaffold runops project"
```

採用した simulator / site / launcher、base input、最初の milestone、資源条件の判断は
`runo research append` に短く残す。

## Done report

- project root、simulator、site / launcher、doctor の結果
- 作成・更新した campaign / case / survey / run と検証結果
- baseline commit の状態
- 次に自然な 2-4 個の依頼例
