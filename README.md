<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Nkzono99/runops/main/.github/assets/hero-dark.svg">
  <img alt="runops: シミュレーションの run を、エージェントと回す。runo list の例として、running・pending・done の run とノートが並んでいる。" src="https://raw.githubusercontent.com/Nkzono99/runops/main/.github/assets/hero-light.svg" width="100%">
</picture>

<p>
  <a href="https://pypi.org/project/runops/"><img src="https://img.shields.io/pypi/v/runops?color=0e6e68&label=pypi" alt="PyPI"></a>
  <a href="https://pypi.org/project/runops/"><img src="https://img.shields.io/pypi/pyversions/runops?color=3a6b8c" alt="Python"></a>
  <a href="https://github.com/Nkzono99/runops/actions/workflows/ci.yml"><img src="https://github.com/Nkzono99/runops/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Nkzono99/runops/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-5b6670" alt="License"></a>
</p>

runops は HPC / Slurm のシミュレーションを run directory 単位で記録し、AI エージェントが
case の準備から投入、確認、整理までを進めるためのツールです。人が打つコマンドは
`runo init` だけです。

## 会話から run まで

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Nkzono99/runops/main/.github/assets/conversation-dark.svg">
  <img alt="依頼「wc を 0, 0.147, 0.294、phiz を 0, 45 で振って。smoke が通ったら全部投げて。」に対し、エージェントが 6 件の候補を作り、smoke を確認してから投入する。右側に、その裏で実行される runo sweep・runo new --scratch・runo sync のコマンドが並ぶ。" src="https://raw.githubusercontent.com/Nkzono99/runops/main/.github/assets/conversation-light.svg" width="100%">
</picture>

## はじめる

```bash
uv tool install runops
mkdir lunar-sheath && cd lunar-sheath
runo init
```

`runo init` は計算機の種類と使う simulator を尋ねます。計算機はホスト名から推定するので、
京大スパコンのログインノードなら Enter で進めます。できた directory で Codex か Claude Code を
起動して、調べたいことを話しかけてください。設定を後から変えたいときも、エージェントに伝えれば
`runops.toml` を書き換えます。

## 頼めること

| やりたいこと | 頼み方の例 |
|---|---|
| case を用意する | cookbook の平板シースを元に case を作って。gr20001a に 800 並列、120 時間で |
| 試してから本計算 | 100 step だけ smoke で試して、通ったら wc を 3 通りに振った候補を見せて |
| 様子を見る | 先週投げた run の状況を見て。失敗していたら原因をノートに残して |
| 続きを流す | R20261015-0003 の続きを 2 倍の step で |
| 片付ける | 古い run を整理して。消すものと archive するものを先に見せて |
| simulator を足す | パッチを当てた ~/BEACH-dev をビルドして、別の simulator として登録して |
| 更新する | runops と simulator を最新にして |
| v1 から移る | この project を runops v2 に移行して（`runo migrate-v1` を dry-run で確認してから） |

投入、削除、整理、移行の前には、エージェントが対象と資源量を示して確認を取ります。
場面ごとの流れは [使い方ガイド](https://github.com/Nkzono99/runops/blob/main/docs/guide.md) にあります。

## project の中身

```text
lunar-sheath/
├── runops.toml                  site・simulator・launcher の設定
├── cases/
│   └── flat/                    case.toml と base 入力ファイル
├── runs/
│   ├── flat/
│   │   ├── R20261015-0002--wc0.147/
│   │   │   ├── manifest.toml    状態・由来・params・ノート
│   │   │   ├── input/           凍結した入力
│   │   │   ├── submit/job.sh
│   │   │   ├── work/            Slurm のログと出力
│   │   │   └── analysis/
│   │   └── wc-phiz-scan/        sweep はまとめて 1 階層
│   ├── _scratch/                smoke / debug（期限付き）
│   └── _archive/                archive した run
├── LOG.md                       run をまたぐ結論と次の判断
├── notes/                       再利用する知見
└── AGENTS.md, .agents/skills/, .claude/skills/
```

run は ID が変わらないので、directory を移動してもエージェントは見つけられます。
`work/` は Git の対象外で、`manifest.toml`、`input/`、`job.sh` は Git で追えます。

## 対応 simulator

| simulator | package | 状態 |
|---|---|---|
| MPIEMSES3D | `mpiemses3d-tools` ≥ 4.20 | adapter とエージェント向け skill を同梱 |
| BEACH | `beach-bem` ≥ 3.0 | adapter とエージェント向け skill を同梱 |
| その他 | 自作の adapter、または `generic` | [adapter ガイド](https://github.com/Nkzono99/runops/blob/main/docs/adapter.md) |

---

[使い方ガイド](https://github.com/Nkzono99/runops/blob/main/docs/guide.md) ·
[リファレンス](https://github.com/Nkzono99/runops/blob/main/docs/reference.md) ·
[adapter ガイド](https://github.com/Nkzono99/runops/blob/main/docs/adapter.md) ·
[SPEC](https://github.com/Nkzono99/runops/blob/main/SPEC.md) ·
[開発に参加する](https://github.com/Nkzono99/runops/blob/main/AGENTS.md) ·
Apache-2.0
