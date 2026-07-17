---
name: setup-campaign
description: Use when the requested outcome is a campaign.toml that defines the research hypothesis, variables, observables, and scope.
---

# 研究意図を campaign.toml に定着させる

## 実行契約

- **Goal**: 自然言語の研究テーマを検証可能な campaign 定義にする
- **Done**: hypothesis、variables、observables、units、reasons が揃い、検証結果を報告できる
- **Budget**: 既存 `campaign.toml` とユーザー入力を基本sourceにし、未解決の物理的意味だけ専門skillで補う
- **Invariant**: campaign設計で閉じ、case、survey、run生成、plugin確認へ自動で進まない

## Outcome loop

既存`campaign.toml`とユーザー入力からtheme、hypothesis、independent / dependent / fixed /
controlled、observablesを抽出する。parameter名、物理範囲、unitの未解決gapだけを該当simulator /
environment skillへ渡し、研究の意味を変える不足情報はまとめて確認する。更新後にprojectの
structure validationを一度実行し、Done、仮定、未解決点を返す。

## campaign contract

| section | 必須内容 |
|---|---|
| `[campaign]` | `name`, `description`, `hypothesis`, `simulator` |
| `[variables.*]` | `role`, parameterの意味、`unit`, `reason`, independentなら`range`または`values` |
| `[observables.*]` | source、測定量の説明、`unit` |

既存のproject identityである`name`と`simulator`は入力として扱う。変更がGoalに含まれる場合は、
影響するcase / surveyをDone reportに列挙する。

```toml
[variables.ray_zenith_angle_deg]
role = "independent"
values = [0, 20, 40, 60, 80]
unit = "deg"
reason = "照射角による表面電位の変化を測る"

[observables.surface_potential]
source = "work/phisp*.h5"
description = "表面電位分布"
unit = "V (normalized)"
```

campaignの作成がDone。case / survey作成やresearch journalへの記録は、それをGoalに含む依頼で
対応するskillへ進める。
