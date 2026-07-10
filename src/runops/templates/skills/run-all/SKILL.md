---
name: run-all
description: Generate and submit all runs from a survey. Use when ready to launch a parameter sweep.
---

# Pilot gate 付きでサーベイを生成・投入する

## 手順

1. Active Experiment Portfolio と proposal path、pilot matrix、cost ceiling を確認
2. `runo runs sweep` で run 生成し、`runo runs list` で exact pilot run_id を確認
3. 対応する review に `Decision: EXPAND` がなければ、明示承認後に pilot run だけを
   `runo runs submit <RUN>` で投入して停止する
4. pilot 完了後は `{{ skill_prefix }}review-pilot` で
   `research/reviews/<date>-<topic>.md` を作る
5. review の proposal / run_id / criteria、文字列 `Decision: EXPAND`、portfolio の
   review path と decision が一致する場合だけ full submit plan を作る
6. `runo runs submit --dry-run --all` で投入対象と skip を確認する
7. remaining run 数、queue、資源量、cost ceiling、実行 command を報告して明示確認を取る
8. `runo runs submit --all` で full submit する

```bash
runo runs sweep $ARGUMENTS
runo runs list $ARGUMENTS
cd $ARGUMENTS
# review がない場合: proposal に列挙した pilot だけを投入して停止
runo runs submit <pilot-run-id> -qn <queue>

# review に Decision: EXPAND がある場合だけ full submit plan へ進む
runo runs submit --dry-run --all -qn <queue>
# → run 数、skip、queue、資源量を報告してから投入
runo runs submit --all -qn <queue>
# 会話上で明示確認済みなら CLI prompt を省略
runo runs submit --all --yes -qn <queue>
```

## 注意

- `runs submit --all` は破壊的操作ではないが、HPC 資源・queue・quota に影響する高コスト操作
- `--yes` は CLI prompt を省略するだけで、pilot review gate を省略しない
- review が `REVISE`, `STOP`, `WAIT`、または欠落なら full submit を行わない
- 初回の大規模 survey と EXPAND 後の full submit は承認を取る
- policy や環境で bulk submit が止まった場合、個別 submit に分解して迂回しない。
  止まった理由と予定していた command をユーザーへ返す

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
