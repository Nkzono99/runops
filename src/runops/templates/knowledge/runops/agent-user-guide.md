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
- case は `runo case new` で生成し、run は `runo runs create` / `runo runs sweep` で生成する
- `runs/**/manifest.toml`, `input/`, `submit/`, `work/` は直接編集しない

## 最初に読むもの

1. `uvx --from runops runo context --json`
2. `uvx --from runops runo plugins --check` と `uvx --from runops runo plugins --json`
3. `campaign.toml`
4. `research/agenda.md`
5. 関連する `cases/**/case.toml` と `runs/**/survey.toml`
6. `.runops/facts.toml` と `.runops/knowledge/candidates/facts/`
7. 必要なら `runo runs status` / `runo runs log -e`

## 知識と記録

- 時系列の作業ログは `runo notes append` で `notes/YYYY-MM-DD.md` に残す
- 現在の高レベルな研究判断は `research/agenda.md` に残す
- 整理済み知見は `runo knowledge save` / `runo knowledge add-fact` を使う
- `.runops/knowledge/` は生成済み Agent context であり、手で整形しない
- simulator cookbook や長文 workflow は推奨 Codex plugin / explicit knowledge
  source を優先し、`refs/` mirror は存在する場合だけ fallback として使う

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
project の note や HarnessOps feedback に記録し、ユーザーに相談してから issue
または PR に進める。runops 本体を修正したい場合は、別途 source checkout を用意し、
project の研究作業と混ぜない。
