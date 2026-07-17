---
name: setup-plugins
description: Use when the user requests plugin setup or the current Goal depends on a recommended delegated capability that is unavailable.
---

# Goalに必要なCodex pluginを利用可能にする

## 実行契約

- **Goal**: 指定pluginまたはdelegated capabilityをinstall / enable / activation可能な状態にする
- **Done**: 対象plugin、実施状態、残るuser action、activation方法、委譲roleを報告できる
- **Budget**: requested capabilityに関係する推薦だけを扱い、metadata確認と検証を各1回

## Inventory

```bash
uvx --from runops runo plugins --json
```

`recommendations`からname、visibility、capabilities、install_hint、activation_hintを読み、
requested capabilityを提供する最小のplugin集合を選ぶ。

## State transition

1. project metadataから対象pluginと公式install / activation導線を選ぶ
2. project外の変更は、変更先、理由、command、rollbackを示してcheckpointを得る
3. `install_hint`またはplugin公式UI / installerでinstall・enableする
4. `activation_hint`に従い、restart / new threadなどの残作業を確定する
5. metadataを一度検証してDoneを返す

```bash
uvx --from runops runo plugins --check
```

`plugins --check`はproject推薦metadataの検査であり、user-local runtimeへのロード確認は
plugin managerまたは新しいthreadで行う。

## Safety invariant

- install / activationのsourceは`install_hint`, `activation_hint`, plugin公式README
- token、private URL、credentialは表示・記録対象から除外する
- user-local config、plugin cache、marketplaceはproject外変更としてcheckpoint対象にする
- `curl | sh`、remote process substitution、履歴破壊、広域削除はinstall経路に採用しない
- Codex hooks は experimental なplugin-provided hookとして扱い、提供元、発火条件、失敗影響、無効化方法を確認する
- runops project 側で hook を自作しない。plugin公式template / manifest / commandをsourceにする

## Availability routes

| 状態 | Doneへの経路 |
|---|---|
| exact CLI hint | command availability確認 → checkpoint → 実行 |
| plugin manager UI | 選ぶplugin名とcapabilityを報告し、user actionをDoneに含める |
| private-or-gated | 最小限の認証確認 → 公式導線。権限不足はlocal skill / knowledge sourceを代替候補にする |
| plugin-provided hook | 公式installer / manifestから設定し、rollbackを報告する |

Done reportにはinstall / enable済み、残るuser action、restart要否、delegated roleを含める。
初期設計を続ける場合は`{{ skill_prefix }}setup-runops`を次のGoal候補として報告し、このskillは
plugin readinessで完了する。
