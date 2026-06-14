---
name: runops-reference
description: runops CLI command reference and usage patterns. Use when working with runops commands, creating runs, submitting jobs, or checking status.
user-invocable: false
---

# runops コマンドリファレンス

詳細なフィールド定義は `runo <command> --help`、schemas、または installed
runops package に同梱された generated guide を参照。

project 側で実行するときの標準形は `uvx --from runops runo <command>`。
以下の例では読みやすさのため `runo` と省略している。

## 現在地を把握する

```bash
runo context --json      # project / campaign / runs / failures の概要
runo lint                # project state の health check
runo lint --scope structure,analysis,knowledge,plugins
runo runs list           # run 一覧
runo runs list runs/a runs/b  # 複数 PATH 指定
runo runs jobs           # submitted/running のジョブ一覧
runo runs jobs --all     # 全 run のジョブ情報
runo runs jobs -w 30     # 30 秒ごとに自動更新
runo runs dashboard runs/<survey>     # 複数 run の進捗 (state, step/N, %, slurm)
runo runs dashboard runs/<survey> -w 30
runo runs dashboard runs/<survey> --all  # completed/failed も表示
runo runs history        # 投入履歴 (最新20件)
runo runs history -n 0   # 全件
```

## runops 更新後の移行

```bash
runo update-harness --plan
runo update-harness --apply-chain
runo migrate list
runo migrate show M0-0001
runo migrate apply M0-0001 --dry-run
```

Harness 更新は `.runops/harness.lock` の `runops_version` から versioned chain を踏む。
Project-state migration guide は release note、`runo migrate list/show`、または別の runops
source checkout の `docs/migrations/` を参照する。
CLI で扱えるのは定型 migration だけ。判断が必要なものは `migrate-runops` skill で扱う。

## Case を作る

```bash
# simulator 指定で cases/<sim>/ 以下に自動生成
runo case new my_case -s emses
# cases/<sim>/ 以下なら simulator を自動検出
cd cases/emses && runo case new my_case
# 小さな bundled テンプレートで生成 (refs/ の rich テンプレートを使わない)
runo case new my_case -s emses --minimal
# survey.toml stub も同時生成
runo case new my_case -s emses --survey
# 生成先を明示指定
runo case new my_case -s emses -d /path/to/dest
```

EMSES の場合、`runo case new` は best-effort で `emu generate -u` を呼んで
生成された `plasma.toml` の `[meta.physical]` を埋める (`emu` が PATH に
入っていなければ silent skip)。

## Run を作る

```bash
# case から単一 run を生成 (cwd に生成)
cd runs/test/basic && runo runs create my_case
# 生成先を指定
runo runs create my_case --dest runs/test/basic
```

## Survey を展開する

```bash
# survey.toml から全 run を生成
runo runs sweep runs/sheath/angle_scan
# cwd が survey ディレクトリなら引数省略可
cd runs/sheath/angle_scan && runo runs sweep
# 生成せずに件数・パラメータ組合せ・概算 core-hour だけ確認
runo runs sweep runs/sheath/angle_scan --dry-run
```

## Run を投入する

```bash
# 個別 run
cd runs/test/basic/R20260330-0001
runo runs submit
runo runs submit -qn compute       # queue 指定
runo runs submit --dry-run          # 確認のみ

# survey 全体
cd runs/sheath/angle_scan
runo runs submit --all
runo runs submit --all -qn compute
runo runs submit --all --yes       # 会話上で確認済みの場合のみ
```

## 状態確認と同期

```bash
runo runs status                    # cwd の run の状態 (manifest 更新なし)
runo runs status R20260330-0001 R20260330-0002  # 複数を一気に
runo runs status runs/sheath/angle_scan         # survey 配下を一括で
runo runs sync                      # Slurm 状態を manifest に反映
runo runs sync runs/sheath/angle_scan           # survey 一括 sync
                                                  # (created な run は silent skip)
```

## ログ

```bash
runo runs log            # stdout (デフォルト20行)
runo runs log -e         # stderr
runo runs log -n 100     # 行数指定
runo runs log -f         # follow (tail -f 相当)
```

## Clone / Extend

```bash
# clone
runo runs clone --dest runs/test/variant
runo runs clone --set dt=0.5e-8 --set nx=128  # source case から再生成

# 完了 run から continuation
runo runs extend
runo runs extend --nstep 200000
runo runs extend --run         # 生成して即投入

# retry / partial output
runo runs retry --plan         # 状態を戻さず retry intent を記録
runo runs retry -a walltime=24:00:00
runo runs retry --and-submit
```

## 解析

```bash
runo analyze summarize                          # run の要約
runo analyze collect runs/sheath/angle_scan     # survey 集計 artifacts (CSV/JSON/report)
runo analyze plot runs/sheath/angle_scan --list-columns
runo analyze plot runs/sheath/angle_scan --list-recipes
runo analyze plot runs/sheath/angle_scan --recipe completion-vs-dt
runo analyze plot runs/sheath/angle_scan --x param.angle --y ion_flux
runo analyze new-comparison "landau model comparison" --source runs/sheath/angle_scan
runo analyze export runs/sheath/angle_scan --paper draft-a
```

## 知見管理

```bash
# 人向け知見
runo knowledge save name -t result -s emses -m "..."
runo knowledge save name -t constraint -s emses --tags "stability,cfl" -m "..."
runo knowledge list
runo knowledge list -s emses -t constraint

# 機械可読 fact
runo knowledge add-fact "claim" -t constraint -s emses \
  --param-name tmgrid.dt --scope-text "baseline scan" \
  --evidence-kind run_observation --evidence-ref run:R20260330-0001 \
  -c high --tags "stability,cfl"
runo knowledge facts
runo knowledge facts --local-only
runo knowledge facts --scope emses --tag stability -c medium
runo knowledge promote-fact shared:f004

# 外部 knowledge source
runo knowledge source attach path other-project ../other-project --kind project
runo knowledge source attach git shared-kb https://github.com/u/repo.git
runo knowledge source attach path analysis-notes ../shared-notes --kind insights
runo knowledge source detach other-project
runo knowledge source list
runo knowledge source sync                        # 接続先から知見をインポート
runo knowledge source sync -s emses
```

## 停止・整理・削除

```bash
# 実行中の run を安全に停止 (scancel + sync を一回で)
runo runs cancel             # submitted/running の run を停止
runo runs cancel --yes       # 確認スキップ

# completed → archived → purged の通常フロー
runo runs archive            # completed run を archived にし、既定で runs/_archive/ へ移動
runo runs archive --yes      # 確認スキップ
runo runs archive --keep-in-place  # 移動せず状態だけ archived にする
runo runs archive --move-to runs/_archive_2026  # custom archive root
runo runs purge-work         # work/ の不要ファイル削除 (archived のみ)
runo runs purge-work --yes

# created/cancelled/failed の run ディレクトリをハード削除
# (completed/archived には使えない — archive → purge-work を使うこと)
runo runs delete             # 確認あり
runo runs delete --yes       # 確認スキップ
```

## 任意の refs cookbook を参照する

通常は simulator / environment plugin skill、enabled knowledge、`materials/` を先に参照する。
`runo init --with-refs` などで `refs/` mirror を用意している project だけ、
次の cookbook を fallback として参照できる:

```bash
# entry 一覧 (index.toml)
cat refs/<repo>/cookbook/index.toml

# entry の詳細 (meta.toml)
cat refs/<repo>/cookbook/examples/<category>/<name>/meta.toml

# 入力例
cat refs/<repo>/cookbook/examples/<category>/<name>/input.toml

# fragment
cat refs/<repo>/cookbook/fragments/<category>/<name>/meta.toml
cat refs/<repo>/cookbook/fragments/<category>/<name>/fragment.toml
```

index.toml で `status = "stable"` の entry を選ぶ。
meta.toml の `[recommended].vary_first` がサーベイ軸の候補になる。
`[edit_policy].immutable` は変更しない。
fragment は `[merge]` と `[compatibility]` を確認してから使う。

## 環境

```bash
runo doctor             # 環境検査
runo lint               # project state / Agent context / plugin metadata の health check
runo update-refs        # opt-in refs mirror の更新 + ナレッジ再生成
runo config show        # 設定表示
```
