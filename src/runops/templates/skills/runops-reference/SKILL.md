---
name: runops-reference
description: Select the smallest runops command family when exact CLI routing is needed. Prefer the task-specific skill and read command help only for the selected transition.
user-invocable: false
---

# 目的から runops command を選ぶ

## 実行契約

- **Goal**: 現在地から Done へ進む一つの runops command family を選ぶ
- **Done**: 対象、effect、正確な command を説明できる
- **Budget**: task-specific skill と選んだ command の `--help` だけを読む
- **Invariant**: command選択だけを扱い、隣接phaseや別familyを自動実行しない

project 側の標準形は `uvx --from runops runo <command>`。以下では `runo` と省略する。
正確な option は選択後に一度だけ確認する。

```bash
runo <group> --help
runo <group> <command> --help
```

## Goal routing

| Goal | command / skill |
|---|---|
| project の現在地 | `runo context --json`, `runo triage`, 必要な scope の `runo lint` |
| Experiment admission / decision | `runo experiments create|list|inspect|review|close` |
| case 作成 | `{{ skill_prefix }}new-case` → `runo case new` |
| survey 設計 / read-only plan | `{{ skill_prefix }}survey-design` → `runo runs sweep` |
| selected Run 生成 | `{{ skill_prefix }}create-run` → `runo runs create` または `sweep --apply --point|--all --expect-plan` |
| smoke / debug | `runo test smoke|debug|list|record|clean` |
| pilot / full submit | `{{ skill_prefix }}run-all` → `runo runs submit` |
| state / progress evidence | `{{ skill_prefix }}check-status` → `runo runs sync|status|log` |
| failure diagnosis / retry | `{{ skill_prefix }}debug-failed` → `runo runs retry` |
| run-local / cross-run 解析 | `{{ skill_prefix }}analyze`, `{{ skill_prefix }}summarize-script` |
| research memory / knowledge | `{{ skill_prefix }}research-workspace`, `{{ skill_prefix }}learn` |
| restore / archive / purge / delete | `{{ skill_prefix }}cleanup` |
| harness / migration | `{{ skill_prefix }}update-runops`, `{{ skill_prefix }}migrate-runops` |

full / large survey 全体の submit は直接実行せず `{{ skill_prefix }}run-all` に経路を渡し、pilot evidence、
owning Experiment の `decision=expand`、sealed Result evidence、cost ceiling、承認を entry criteria とする。

## State transition map

```text
question -> experiments create -> active Experiment
survey -> runs sweep -> read-only candidate plan
selected point + plan hash -> runs sweep --apply -> created
case + Experiment -> runs create -> created
case smoke/debug -> test smoke|debug -> T receipt (Runではない)
created -> runs submit -> submitted
submitted/running -> runs sync -> current state + recommended action
completed -> analyze summarize|collect -> analysis evidence
completed -> runs archive -> archived -> runs purge-work
                                -> runs restore -> completed
terminal -> runs review -> reviewed (Result selectionとは別)
claim + evidence -> research seal -> sealed Result
```

各 command の output に recommended command がある場合は、それを次の候補として Goal / Done と
照合する。後続段階が現在の Done に含まれる場合に限って遷移を続ける。
