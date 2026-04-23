---
name: run-all
description: Generate and submit all runs from a survey. Use when ready to launch a parameter sweep.
---

# サーベイの全 Run を生成して投入する

## 手順

1. `runo runs sweep` で run 生成
2. `runo runs list` で確認
3. run 数と queue を報告して承認を取る
4. `runo runs submit --all` で投入

```bash
runo runs sweep $ARGUMENTS
runo runs list $ARGUMENTS
# → run 数と queue を確認してから投入
cd $ARGUMENTS
runo runs submit --all -qn <queue>
```

## 注意

- `run --all` は高コスト操作。事前に plan を出す
- 初回の大規模 survey は承認を取る
- dry-run で確認: `runo runs submit --dry-run --all`

## `{{ skill_prefix }}note` で残すべきこと

投入直前と直後に lab notebook に記録する (後でジョブが化けたとき・物理が
おかしかったとき、何を投入したか辿れるようにする):

- どの survey を、いつ、どの queue に、何 run 投入したか
- 想定 walltime, core-h, 期待される完了時刻
- smoke test の代表 run と判定基準 (これがコケたら全停止)
- 投入前のスナップショット commit hash

```bash
runo notes append "Series A 全投入" - <<'EOF'
runs/series_A_flat_plate/ から 10 run, gr20001a へ投入.
job_id: 4567890..4567899. snapshot commit: 53a7e62.
smoke は R20260330-0001/-0010/-0019 (両端と中央).
完走見込み: 約 8 h × 10 run / 4 並列 = 20 h.
EOF
```
