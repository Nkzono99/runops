<p align="center">
  <img src="https://raw.githubusercontent.com/Nkzono99/runops/main/.github/assets/runops-banner.svg" alt="runops" width="680">
</p>

<p align="center">
  <b>HPC シミュレーションを、AI エージェントとの会話で回す。</b><br>
  case から run を作り、Slurm に投げ、結果と経緯を run ごとに残します。<br>
  人が打つコマンドは <code>runo init</code> だけです。
</p>

<p align="center">
  <a href="https://pypi.org/project/runops/"><img src="https://img.shields.io/pypi/v/runops?color=6366f1&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/runops/"><img src="https://img.shields.io/pypi/pyversions/runops?color=14b8a6" alt="Python"></a>
  <a href="https://github.com/Nkzono99/runops/actions/workflows/ci.yml"><img src="https://github.com/Nkzono99/runops/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Nkzono99/runops/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-8b949e" alt="License"></a>
</p>

---

## こんなふうに使います

> **あなた**　平板シースの case で、wc を 0, 0.147, 0.294、phiz を 0, 45 で振った本計算の候補を見せて。投入は確認してから。
>
> **エージェント**　6 件の候補を作りました（`runs/flat/wc-phiz-scan/`、計 約 57,600 core-hours、gr20001a / 800 並列 / 12 時間）。先に 100 step の smoke を 1 件流して入力を確かめますか？それとも 6 件をそのまま投入しますか？
>
> **あなた**　smoke を流して、通ったら全部投げて。
>
> **エージェント**　smoke は 3 分で正常終了しました。6 件を投入しました（job 8184100–8184105）。終わる頃にもう一度確認します。

<details>
<summary>このときエージェントが実行しているコマンド</summary>

```bash
runo sweep flat --set plasma.wc=0,0.147,0.294 --set plasma.phiz=0,45 --label wc-phiz-scan
runo new flat --scratch --set jobcon.nstep=100 --why "入力の確認" --submit
runo sync && runo log R20261015-0007 --err
runo sweep flat --set plasma.wc=0,0.147,0.294 --set plasma.phiz=0,45 \
     --label wc-phiz-scan --why "wc と磁場角の依存" --apply --submit -y
```

</details>

## 特長

- **run が主役**　1 回の実行は 1 つの directory。入力、job.sh、出力、ノート、由来が `manifest.toml` と一緒に残ります。
- **増えても散らからない**　値違いは case を増やさず run として作ります。一覧は実行中と直近の run だけ。古い run や期限切れの smoke は整理候補として提案されます。
- **simulator が知識を連れてくる**　MPIEMSES3D や BEACH の package を入れると、adapter とエージェント向け skill が project に入ります。plugin の install は要りません。
- **確認してから動く**　投入、削除、整理の前に、対象と資源量を示して確認を取ります。「作って」は作成だけ、「試して」は短い smoke まで。

## はじめる

```bash
uv tool install runops
mkdir lunar-sheath && cd lunar-sheath
runo init emses --site camphor
```

`simulator` と `--site` はどちらも省略できます。できた directory で Codex や
Claude Code を起動し、調べたいことを伝えてください。生成された `AGENTS.md` と
skill が、エージェントに runops の使い方を教えます。

## 頼めること

| やりたいこと | 頼み方の例 |
|---|---|
| case を用意する | 「cookbook の平板シースを元に case を作って。gr20001a に 800 並列、120 時間で」 |
| 試してから本計算 | 「100 step だけ smoke で試して、通ったら wc を 3 通りに振った候補を見せて」 |
| 様子を見る | 「先週投げた run の状況を見て。失敗していたら原因をノートに残して」 |
| 続きを流す | 「R20261015-0003 の続きを 2 倍の step で」 |
| 片付ける | 「古い run を整理して。消すものと archive するものを先に見せて」 |
| simulator を足す | 「パッチを当てた ~/BEACH-dev をビルドして別 simulator として登録して」 |
| 更新する | 「runops と simulator を最新にして」 |
| v1 から移る | 「この project を runops v2 に移行して（`runo migrate-v1` を dry-run で確認してから）」 |

## project に残るもの

```text
lunar-sheath/
├── runops.toml          site・simulator・launcher の設定
├── cases/flat/          case.toml と base 入力ファイル
├── runs/
│   ├── flat/
│   │   └── R20261015-0002--wc0.147/
│   │       ├── manifest.toml   状態・由来・params・ノート
│   │       ├── input/  submit/job.sh  work/  analysis/
│   ├── _scratch/        smoke / debug（期限付き）
│   └── _archive/        archive した run
├── LOG.md               run をまたぐ結論と次の判断
├── notes/               再利用する知見（1 topic 1 file）
└── AGENTS.md  .agents/skills/  .claude/skills/
```

## 対応 simulator

| simulator | package | 状態 |
|---|---|---|
| MPIEMSES3D | `mpiemses3d-tools` ≥ 4.20 | adapter と skill を同梱 |
| BEACH | `beach-bem` | 次のリリースで同梱。それまでは runops 同梱の移植版 adapter を使用 |
| その他 | 自作の adapter、または `generic` | [adapter ガイド](https://github.com/Nkzono99/runops/blob/main/docs/adapter.md) |

## ドキュメント

- [リファレンス](https://github.com/Nkzono99/runops/blob/main/docs/reference.md)：`runops.toml`、`case.toml`、`manifest.toml`、全コマンド（主にエージェントと開発者向け）
- [adapter ガイド](https://github.com/Nkzono99/runops/blob/main/docs/adapter.md)：simulator package に adapter と skill を同梱する方法
- [SPEC](https://github.com/Nkzono99/runops/blob/main/SPEC.md)：設計と決定事項

<details>
<summary>開発</summary>

```bash
git clone https://github.com/Nkzono99/runops.git && cd runops
uv sync --dev
uv run pytest
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run mypy src/
```

</details>

---

<p align="center"><sub>Apache-2.0 · Made for simulation research on HPC</sub></p>
