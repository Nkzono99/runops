<!-- Auto-generated from the runops package that last ran update-harness. Do not edit. -->

# runops Agent ユーザーガイド

この project は runops で管理されている。Agent はまず
`uvx --from runops runo context --json`
で現在地を確認し、必要に応じて `runo --help` / `runo <command> --help` と
project-local skill を参照する。

## 基本原則

- run ディレクトリが主単位: すべての操作は run_id または run ディレクトリを基点にする
- manifest.toml が正本: run の状態・由来・provenance は manifest に記録される
- cwd ベース: 引数省略時はカレントディレクトリをデフォルトターゲットにする
- formal questionは`runo experiments create`、caseは`runo case new`で生成する
- `runo runs sweep`の既定はread-only plan。Run生成には`--apply`、`--point|--all`、`--expect-plan`が必要
- smoke / debugは`runo test smoke|debug`で`.runops/test-runs/T...`へ分離する
- `runs/**/manifest.toml`, `input/`, `submit/`, `work/` は直接編集しない

## 最初に読むもの

1. `uvx --from runops runo context --json`
2. `uvx --from runops runo triage --json`
3. `uvx --from runops runo plugins --check` と `uvx --from runops runo plugins --json`
4. `campaign.toml` と owning `experiments/E...toml`
5. `research/CURRENT.md` と `runo research status`
6. 関連する `cases/**/case.toml` と `runs/**/survey.toml`（まずread-only plan）
7. `.runops/facts.toml` と `.runops/knowledge/candidates/facts/`
8. 必要なら `runo runs status` / `runo runs log -e`

## 知識と記録

- 時系列の作業ログは `runo research append` で bounded journal に残す
- 現在の高レベルな研究判断は `research/CURRENT.md` に残す
- 残す解析は `research/results/` に明示昇格し、説明を README 1 枚に集約する
- Resultのclaim/evidenceをsealし、Run reviewとevidence selectionを同一視しない
- Run evidenceはcompleted相当、理由付きreview、identity / source / baseline / input snapshotを確認する
- sealed ResultがincludeしたRun-owned outputを`purge-work`で削除しない
- T IDと`.runops/test-runs/**`をscientific Result evidenceにしない
- case / survey `notes.md`とRun `analysis/notes.md`を新規作成せず、途中proseは`.runops/work/`へ置く
- 整理済み知見は `runo knowledge save` / `runo knowledge add-fact` を使う
- `.runops/knowledge/` は生成済み Agent context であり、手で整形しない
- simulator cookbook や長文 workflow は推奨 Codex plugin / explicit knowledge
  source を優先し、`refs/` mirror は存在する場合だけ fallback として使う
- 推奨 plugin の install / enable / plugin-provided hook 導線を整える必要があれば
  `{{ skill_prefix }}setup-plugins` を使う

## runops 自体の確認

runops CLI は標準では `uvx` で実行する。version と実体は次で確認する。

```bash
uvx --from runops runo --version
uvx --from runops python -c "import runops; print(runops.__file__)"
uvx --from runops python -c "from importlib import metadata; print(metadata.version('runops'))"
```

project に `tools/runops/` があるとは限らない。通常の project では runops は
project `.venv/` へ常駐 install せず、CLI 実行時に `uvx --from runops runo ...`
で解決する。`.venv/` は simulator package や解析依存など runtime 用に使う。
Agent 向けの参照情報はこの `.runops/knowledge/runops/` 配下に生成される。

## runops へのフィードバック

runops の bug、分かりにくい error、足りない workflow を見つけたら、まず
project の journal に記録し、ユーザーに相談してから issue
または PR に進める。runops 本体を修正したい場合は、別途 source checkout を用意し、
project の研究作業と混ぜない。
