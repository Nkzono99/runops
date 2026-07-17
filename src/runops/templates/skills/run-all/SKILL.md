---
name: run-all
description: Generate and submit all runs from a survey. Use when ready to launch a parameter sweep.
---

# Pilot 確認付きでサーベイを生成・投入する

## 手順

1. `research/CURRENT.md`、対応する result README、pilot matrix、cost ceiling を確認
2. `runo runs sweep` で run 生成し、`runo runs list` で exact pilot run_id を確認
3. pilot result の人による確認がなければ、明示承認後に pilot run だけを
   `runo runs submit <RUN>` で投入して停止する
4. pilot 完了後は `{{ skill_prefix }}research-workspace` で、対応する result README に
   evidence と解釈を、`research/CURRENT.md` に現在判断を残す
5. pilot run_id、判定基準、result evidence、CURRENT の判断が一致する場合だけ
   full submit plan を作る
6. `runo runs submit --dry-run --all` で投入対象と skip を確認する
7. remaining run 数、queue、資源量、cost ceiling、実行 command を報告して明示確認を取る
8. `runo runs submit --all` で full submit する
9. submit 後は job_id を報告して返す。自動で待機・sync・log 確認を始めない

```bash
runo runs sweep $ARGUMENTS
runo runs list $ARGUMENTS
cd $ARGUMENTS
# human-reviewed pilot result がない場合は pilot だけを投入して停止
runo runs submit <pilot-run-id> -qn <queue>

# CURRENT に full survey の明示判断がある場合だけ plan へ進む
runo runs submit --dry-run --all -qn <queue>
# → run 数、skip、queue、資源量を報告してから投入
runo runs submit --all -qn <queue>
# 会話上で明示確認済みなら CLI prompt を省略
runo runs submit --all --yes -qn <queue>
# → job_id を報告して終了。明示依頼がなければ startup check は行わない
```

## 注意

- `runs submit --all` は破壊的操作ではないが、HPC 資源・queue・quota に影響する高コスト操作
- `--yes` は CLI prompt を省略するだけで、pilot の人による確認を省略しない
- pilot evidence や判断が不足する場合は個別 submit 分解で迂回しない
- CURRENT の判断が `REVISE`, `STOP`, `WAIT`、または欠落なら full submit を行わない
- 初回の大規模 survey と EXPAND 後の full submit は承認を取る
- 「smoke run を投入して」だけでは投入後の監視を始めない。正常動作や数 step の
  確認まで依頼された場合だけ `{{ skill_prefix }}check-status` の startup check へ進む
- policy や環境で bulk submit が止まった場合、個別 submit に分解して迂回しない。
  止まった理由と予定していた command をユーザーへ返す

## `{{ skill_prefix }}research-workspace` で残すべきこと

投入直前と直後に lab notebook に記録する (後でジョブが化けたとき・物理が
おかしかったとき、何を投入したか辿れるようにする):

- どの survey を、いつ、どの queue に、何 run 投入したか
- 想定 walltime, core-h, 期待される完了時刻
- smoke test の代表 run と判定基準 (これがコケたら全停止)
- 投入前のスナップショット commit hash

```bash
runo research append "Series A 全投入" "$(cat <<'EOF'
runs/series_A_flat_plate/ から 10 run, gr20001a へ投入.
job_id: 4567890..4567899. snapshot commit: 53a7e62.
smoke は R20260330-0001/-0010/-0019 (両端と中央).
完走見込み: 約 8 h × 10 run / 4 並列 = 20 h.
EOF
)"
```
