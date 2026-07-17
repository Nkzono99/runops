---
name: release
description: Use when the requested outcome is a tagged simulation-project milestone or a release-readiness assessment.
---

# project milestoneをimmutableなtagにする

## 実行契約

- **Goal**: 指定campaign phase / experiment batchをrelease assessmentまたはannotated tagにする
- **Done**: readiness、tag、主要result、source commit、未解決事項を日本語で報告できる
- **Budget**: 一つのmilestoneとtag。前回tag以降のevidenceだけを集約する
- **Invariant**: active jobと未追跡変更を隠さず、archive、commit、pushを暗黙に連鎖しない

## Goal routing

| requested outcome | route |
|---|---|
| readiness only | run state、Git state、result evidence、既存tagを報告 |
| local milestone | scoped commitが必要なら作成 → annotated tag |
| remote publication | local milestone完了後、明示承認を得てpush |

```bash
runo runs list .
git status --short
git tag --list 'v*' --sort=-v:refname
git log <previous-tag>..HEAD --oneline
```

release summaryには目的、対象case / survey / run、主要知見、evidence path、既知の失敗・限界、
次の候補を含める。本文とannotated tag messageは日本語、commit messageは英語にする。

```bash
git tag -a <tag> -m "<日本語summary>"
```

未コミット変更を含める場合は対象を列挙してscoped commitを作る。completed runのarchiveは
`{{ skill_prefix }}cleanup`、lab notebook記録は`{{ skill_prefix }}research-workspace`、
`git push origin <branch> --tags`はremote publicationをGoalに含む場合だけ実行する。
