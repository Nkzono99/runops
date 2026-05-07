---
name: note
description: "Append a timestamped, context-complete entry to today's lab notebook in notes/YYYY-MM-DD.md. Use throughout preparation, execution, debugging, visualization, and analysis. Entries must be concise but recoverable: include minimal context, model/run references, evidence paths, and embedded figures when figures were produced."
---

# 実験ノートを 1 件追記する

`{{ skill_prefix }}note` は today's `notes/YYYY-MM-DD.md` に timestamped な実験ノート
entry を append する skill。目的は **その時点の研究判断・観察・解析結果を、
後日の人間と AI Agent が再開できる粒度で残すこと**。

短く書く。ただし、後から読む人が `model 名`、`run ID`、`figure path` だけを見て
前提を推測しなければならない状態にはしない。

## 基本コマンド

```bash
runo notes append "<title>" "<body...>"
```

本文を stdin から渡す:

```bash
runo notes append "<title>" - <<'EOF'
...
EOF
```

書き込み先:

- `notes/YYYY-MM-DD.md` (JST の今日)
- 古い日次 notebook は `notes/history/YYYY/YYYY-MM-DD.md`
- 無ければ `# YYYY-MM-DD — lab notebook` ヘッダ付きで新規作成
- 各 entry は `## HH:MM <title>` で始まる
- append-only。既存 entry は編集しない

関連コマンド:

- `runo notes list` — active と history の lab notebook 日付一覧
- `runo notes show [DATE|today|latest]` — active と history から指定日の内容を表示
- `runo notes archive --older-than 7d` — 古い日次 notebook を history に移す

## ノートの基本原則

1. **Context first**
   - 各 entry の冒頭に、対象 campaign / survey / run / model / simulator / purpose を
     1-3 行で書く。
   - 不明な項目は省略せず、`unknown` または `not checked` と書く。

2. **Model name must not stand alone**
   - `vertical_hole`, `best_model`, `model_v2` のような名前だけで済ませない。
   - model を言及する場合は、同じ entry 内の 1 行定義、または既存の model card /
     report / case / survey への file link を付ける。

3. **Every result needs evidence**
   - 数値・図・結論・異常判定には、根拠となる run、summary、script、figure、CSV、
     manifest、stdout/stderr などの path を付ける。
   - 「見た」「確認した」だけで終わらせず、何を見て何が分かったかを書く。

4. **Figures are first-class note content**
   - 図を生成した場合、原則として Markdown image として note に埋め込む。
   - 図には、何を描いたか、scale/normalization、主要観察、解釈、caveat を添える。
   - 大量の図を生成した場合は、代表図または contact sheet を埋め込み、全 figure path
     を列挙する。

5. **Separate observation from interpretation**
   - `Observation:` には見えた事実を書く。
   - `Interpretation:` には推測・仮説を書く。
   - `Caveat:` には未確認点・代替説明を書く。

6. **Concise, not cryptic**
   - 通常 entry は 6-12 行程度を目安にする。
   - debug / model definition / major analysis は 15-25 行まで許容。
   - 長くなる場合は、note には要点と links を残し、`notes/reports/<topic>.md` に昇格する。

## 推奨 title 形式

title は次の形式に寄せる:

```text
<TYPE> <object> — <claim/action>
```

TYPE は以下のいずれかを推奨:

- `DESIGN` — campaign / case / survey 設計判断
- `MODEL` — model 定義、model 間差分、前提整理
- `EXEC` — run 生成、submit、sync、cancel、rerun
- `STATUS` — job 状態、完走確認、失敗確認
- `ANALYSIS` — summary 収集、数値結果、比較
- `FIGURE` — 図生成、図の読み取り
- `DEBUG` — 異常調査、仮説検証
- `DECISION` — 採用/却下した方針
- `HANDOFF` — 次に読む人/AI のための作業引き継ぎ

例:

```text
FIGURE vertical_hole/R20260424-0002 — rhobk y-center XZ
DEBUG vertical_hole — zsbuf cutoff explains empty shaft
MODEL vertical_hole_v411 — shifted plane-with-circle fix rerun target
HANDOFF vertical_hole_v411_smoke — submitted; next stdout/HDF5 check
```

## Entry の標準フォーマット

通常 entry はこの compact format を使う:

```markdown
Context: campaign=<id/name>; survey=<path/id>; run=<run_id/path or all>; model=<name + 1-line definition/ref>; simulator=<name/version if relevant>; purpose=<why this was done>.

Action: <実行したこと。command/script/対象を含める。>
Evidence: <根拠 path。summary, figure, CSV, manifest, stdout/stderr, script など。>
Observation: <数値・図・ログから直接分かること。>
Interpretation: <現時点の解釈。推測なら推測と明記。>
Caveat/Next: <未確認点、次の一手、停止条件。>
```

すべての entry で全項目が必要なわけではないが、`Context` と `Evidence` は原則として省略しない。

## Model を扱う entry

model が新しく登場する、または model 名だけでは前提が伝わらない場合は、
まず `MODEL` entry を書く。

```markdown
Context: campaign=<id/name>; model=<model_name>; source=<case/survey/report path>; status=<draft|active|deprecated|superseded>.

Definition: <物理モデル・幾何・境界条件・粒子過程・solver/version を 1-3 文で定義。>
Key assumptions:
- <assumption 1>
- <assumption 2>
Key parameters: <重要 params のみ。例: zssurf=200, zsbuf=100, cylinder radius=50, grad_coef=1.0>
Diff from previous: <親 model / 旧 model との差分。無ければ "baseline"。>
Used by: <survey/run paths>
Open questions: <この model の未確認点>
```

model 記述ルール:

- model 名だけを書かない。
- `model=<name>` の後ろに最低 1 行の定義または file link を付ける。
- model が旧 model を置き換える場合は `supersedes=<old_model>` を書く。
- model 差分は「何が変わったか」だけでなく「なぜ変えたか」を書く。
- 複数 model が乱立してきたら、`notes/reports/<topic>_model_map.md` に昇格する。

## Figure を扱う entry

図を生成したら、原則として note に画像を埋め込む。

### 1-4 枚の場合

```markdown
Context: campaign=<id/name>; run=<run/path>; model=<name + definition/ref>; purpose=<what the figure is meant to check>.

Action: <script/command で何を描いたか。>
Figure:
![<alt text: what is plotted, target run, plane/frame>](../runs/.../analysis/figures/<figure>.png)

Caption: <物理量、slice/frame、単位、color scale、normalization、overlay の意味。>
Observation: <図から直接読めること。>
Interpretation: <なぜそう見えるか。>
Caveat/Next: <色範囲、slice 依存、未確認点、次に描く図。>
Artifacts: figure=<path>; script=<path>; data=<path or summary json/csv>.
```

### 5 枚以上の場合

大量の画像を note にそのまま並べない。以下のどちらかにする:

1. contact sheet / panel summary を生成して 1 枚埋め込む
2. 代表図を 1-3 枚埋め込み、全 figure path を `Artifacts:` に列挙する

```markdown
Figure:
![contact sheet: nd1p-nd5p final XZ slices for 10 SW-angle runs](../runs/vertical_hole/summary/figures/density_nd1p_nd5p_contact_sheet.png)

Caption: all 10 runs, final frame, y=ny//2, log10(n [m^-3])=-5.5..1.5, common color scale.
Observation: <全体傾向。>
Interpretation: <物理的含意。>
Artifacts: contact_sheet=<path>; all_figures=../runs/vertical_hole/R*/analysis/figures/density_nd1p_nd5p_log_xz.png; script=<path>; metrics=<path>.
```

## フェーズ別ガイド

### 準備フェーズ: campaign / case / survey design

書くべきこと:

- 研究目的、仮説、観測量
- survey 軸、範囲、解像度、固定した量
- model の定義と旧 model との差分
- 採用した前提と却下した代替案
- 資源見積もり、queue、投入順序
- smoke test の成功条件・失敗条件
- 「自明」と思っている背景条件

推奨 format:

```markdown
Context: campaign=<id/name>; model=<name + definition/ref>; target=<case/survey path>.

Decision: <何を決めたか。>
Rationale: <なぜその値・範囲・設計にしたか。>
Rejected alternatives: <検討したが採用しなかった案。>
Risk: <心配点、前提、失敗時に見るべきもの。>
Next: <次に作る case/survey/run。>
```

### 投入・実行フェーズ

書くべきこと:

- 作成した run / survey
- submit command、queue、資源量、walltime
- simulator version / executable hash / git commit
- dry-run 結果
- job_id、Slurm state
- 成功条件

推奨 format:

```markdown
Context: survey=<path/id>; run=<path/id>; model=<name + definition/ref>; simulator=<version/hash>.

Action: <submit/create/sync した内容。>
Resources: queue=<queue>; nodes=<n>; ntasks=<n>; threads=<n>; walltime=<time>; core-hour=<estimate>.
Evidence: manifest=<path>; job=<job_id>; stdout/stderr=<path if available>.
Success criteria: <step 到達、HDF5 生成、version file、stderr 0 byte など。>
Next: <monitor/sync/analyze の具体操作。>
```

### 解析フェーズ

書くべきこと:

- 実行した解析 command / script
- 対象 run 範囲
- 主要数値と単位
- どの result path が主張を支えるか
- 解釈と未確認点
- 次に必要な図・比較・rerun

推奨 format:

```markdown
Context: survey=<path/id>; runs=<range/all>; model=<name + definition/ref>; observable=<quantity>.

Action: <collect/summarize/plot command。>
Evidence: summary=<path>; metrics=<path>; script=<path>.
Observation: <数値結果。例: min potential decreases from ... to ...>
Interpretation: <物理的解釈。>
Caveat/Next: <未確認点、追加解析。>
```

### Debug / anomaly 調査

書くべきこと:

- 疑った現象
- 期待値と実測値の差
- 確認した仮説
- 否定できた候補
- 残った leading suspect
- 次の検証

推奨 format:

```markdown
Context: issue=<short name>; run=<path/id>; model=<name + definition/ref>; symptom=<observed anomaly>.

Expected: <本来どう見えるはずか。>
Observed: <実際に何が見えたか。>
Checks:
- <check 1: result>
- <check 2: result>
Ruled out: <否定できた原因。>
Leading suspect: <現時点の最有力仮説。>
Evidence: <source code/docs/input/figure/log paths>
Next: <次の検証。>
```

### Handoff

長い debug、複数 model 比較、日をまたぐ作業の前には `HANDOFF` entry を書く。

```markdown
Context: topic=<topic>; current_state=<one-line summary>.

Known:
- <確定したこと>
- <確定したこと>
Unknown:
- <未確認点>
Next actions:
1. <次に実行する具体操作>
2. <判断基準>
Key artifacts:
- <important path>
- <important path>
Do not forget:
- <落とし穴、前提、注意点>
```

## 書いてよいもの / 書かないもの

書いてよいもの:

- 作業ログ
- 判断理由
- model 定義・model 差分
- run/survey 作成・投入・状態
- 解析結果
- 可視化図とその読み取り
- debug の検証過程
- TODO / next action
- user との議論で生じた論点

書かないもの:

- 論文 PDF / manual / large source excerpt → `materials/`
- 整理済み long-form explanation → `notes/reports/`
- atomic で再利用したい fact → `{{ skill_prefix }}learn` / `.runops/facts.toml`
- 個別 run の curated 解析出力 → `runs/<run>/analysis/`
- 大量の raw stdout 全文 → 必要箇所だけ引用し、全文 path を貼る

## 昇格ルール

entry が 3 件以上にまたがって同じ story を形成したら、`notes/reports/<topic>.md`
へ昇格する。

昇格候補:

- model 定義が複数回参照される
- debug の結論が今後の設計に影響する
- 図と解釈が publication / presentation に使えそう
- survey 結果が campaign の主要知見になる
- 次の AI Agent が頻繁に参照すべき前提になった

昇格後も daily note は消さない。daily note には report path を追記するだけでよい。

## Quality gate before append

`runo notes append` の直前に、以下を確認する:

- title は `TYPE object — action/claim` になっているか
- `Context:` に campaign / survey / run / model / purpose の最低限があるか
- model 名だけで終わっていないか
- command / script / output path / manifest / summary などの evidence があるか
- 図を生成した場合、Markdown image と caption/observation/interpretation があるか
- 数値には単位・対象 run・frame/slice があるか
- observation と interpretation が混ざっていないか
- next action または stop condition があるか
- 不明点を曖昧に省略せず、`unknown` / `not checked` として残したか

## Example: figure entry

```bash
runo notes append "FIGURE vertical_hole/R20260424-0002 — rhobk y-center XZ" - <<'EOF'
Context: campaign=S20260417-sw-angle; survey=runs/vertical_hole; run=R20260424-0002; model=vertical_hole = flat surface z=200 + holed planes z=240/300 + open cylinder sidewall z=240..300; purpose=check whether the apparent z=300 charge plane is a boundary cap or particle-cutoff artifact.

Action: Rendered final-frame `rhobk` on the y-center XZ plane (`y=100`) with geometry overlays.
Figure:
![rhobk y-center XZ slice for R20260424-0002 with z=200/240/300 and sidewall overlays](../runs/vertical_hole/R20260424-0002/analysis/figures/rhobk_ycenter_xz.png)

Caption: `rhobk` [C/m^3], final frame, robust clipping at +/-1.1248e-10 C/m^3; overlays show z=200 flat surface, z=240/300 holed planes, and x=150/250 sidewalls.
Observation: Nonzero structure appears near the z=300 plane; extrema are -1.3114e-09 .. 1.4258e-09 C/m^3.
Interpretation: This is more consistent with the zssurf+zsbuf=300 particle cutoff or accumulated/anti-particle deposition than with open-cylinder caps.
Caveat/Next: Confirm against particle density slices and source code path for boundary construction.
Artifacts: figure=runs/vertical_hole/R20260424-0002/analysis/figures/rhobk_ycenter_xz.png; script=runs/vertical_hole/summary/render_rhobk_xz.py.
EOF
```

## Example: model entry

```bash
runo notes append "MODEL vertical_hole_v411 — shifted plane-with-circle fix rerun target" - <<'EOF'
Context: campaign=vertical_hole SW-angle rerun; model=vertical_hole_v411; source=runs/vertical_hole_v411_smoke/survey.toml; status=active smoke-test target.

Definition: `vertical_hole_v411` is the vertical-hole geometry rerun using MPIEMSES3D v4.11.0, intended to include the shifted `plane-with-circle` boundary collision fix. Geometry inherits the previous vertical_hole setup unless explicitly changed.
Key assumptions:
- Boundary geometry is unchanged from the previous vertical_hole survey.
- The primary intended change is simulator behavior, not physical geometry.
Key parameters: nstep=100 for smoke; dt=0.008; vdthz=60; queue=hpa; ntasks=1000; threads=2.
Diff from previous: simulator updated to MPIEMSES3D v4.11.0; production rerun is blocked until smoke confirms version file, stdout completion, and HDF5 output.
Used by: runs/vertical_hole_v411_smoke/R20260507-0001.
Open questions: Whether the shifted boundary fix changes the apparent z=300 structure and shaft density.
EOF
```

詳細規約: `notes/README.md`
