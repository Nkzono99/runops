# Local runops Patches

生成 project の `tools/runops/` は editable install されているため、current project
で必要になった runops 本体の修正をその場で入れて即利用できる。

## 基本方針

- `update-runops` / `runo update-harness` は `tools/runops` の local changes を
  壊さない。dirty tree、local branch、未 push commit があれば pull せず停止する。
- local patch の正本は `tools/runops` 内の Git branch / commit とする。
- 別枠の mutable patch 履歴はデフォルトでは作らない。stale になりやすい。
- handoff や current project での確認結果は `notes/YYYY-MM-DD.md` に残す。
- 長期化して複数 patch が並ぶ場合だけ、`notes/reports/runops-local-patches.md`
  のような project-local index を作ってよい。

## upstream disposition

local patch 後は、次のどれかに分類する。

| 判定 | 意味 | 次の動き |
|------|------|----------|
| `local-only` | project 固有 | project 側に残す |
| `feedback-issue` | 一部汎用 / 設計が必要 / draft PR には早い | `feedback-runops` で issue |
| `draft-pr` | 実装案も見せたいが設計レビューが必要 | draft PR |
| `ready-pr` | 小さく汎用でテスト済み | 通常 PR |

`feedback-runops` は PR の弱い代替ではなく、local patch を upstream 設計に
変換するための中間レイヤーとして使う。

## upstream に入れないもの

project 側の生成物や研究状態を、そのまま runops 本体に入れない。

- `.agents/skills/*`
- `.claude/skills/*`
- `AGENTS.md`
- `CLAUDE.md`
- `research/*`
- `notes/*`
- `campaign.toml`
- `cases/*`
- `runs/*`

汎用化する場合は、source template / command / docs に戻す。

- project `.agents/skills/foo/SKILL.md` → `tools/runops/src/runops/templates/skills/foo/SKILL.md`
- project `AGENTS.md` / `CLAUDE.md` → `tools/runops/src/runops/templates/harness/`
- project `research/` scaffold → `tools/runops/src/runops/templates/scaffold/research/`
