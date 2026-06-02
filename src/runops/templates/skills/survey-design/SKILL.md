---
name: survey-design
description: Design a parameter survey. Use when planning a parameter sweep, creating survey.toml, or exploring parameter space.
---

# パラメータサーベイを設計する

## 手順

1. 指定されたケースの `case.toml` と入力ファイルを読む
2. simulator plugin skill、enabled knowledge、`materials/` で既存の入力例や制約を探す
3. `refs/` mirror がある場合だけ cookbook を fallback として確認する
   - `cookbook/index.toml` で `tags` と `recommended_for` から候補を絞る
   - 候補の `meta.toml` で `[recommended].vary_first` と `[edit_policy]` を確認
   - `[cost]` から計算コストを見積もる
4. `.runops/facts.toml` で既知の制約を確認する
5. `survey.toml` を生成する
6. 生成される run 数とコスト見積もりを報告する

## cookbook の活用

```bash
# refs mirror がある場合だけ cookbook の entry 一覧を確認
test -f refs/<repo>/cookbook/index.toml && cat refs/<repo>/cookbook/index.toml

# 候補 entry の詳細を確認
test -f refs/<repo>/cookbook/examples/<category>/<name>/meta.toml && \
  cat refs/<repo>/cookbook/examples/<category>/<name>/meta.toml

# 入力例を参照
test -f refs/<repo>/cookbook/examples/<category>/<name>/input.toml && \
  cat refs/<repo>/cookbook/examples/<category>/<name>/input.toml

# 既知の制約を確認
runo knowledge facts
```

## survey の作成

```bash
mkdir -p runs/<category>/<survey_name>
# survey.toml を作成 (フォーマットは runops-reference skill / CLI help 参照)
runo runs sweep runs/<category>/<survey_name>
runo runs list runs/<category>/<survey_name>
```

## 注意

- cookbook の `[edit_policy].immutable` パラメータは survey 軸にしない
- `[edit_policy].sensitive` パラメータを振る場合は理由を plan に書く
- `status = "stable"` の entry をベースにする
- fragment を使う場合は `[merge]` と `[compatibility]` を確認する

## `{{ skill_prefix }}note` で残すべきこと

survey 設計の意思決定は `notes/YYYY-MM-DD.md` に残す:

- どのパラメータ軸を選んだか・なぜか (物理的に何を見たいか)
- スイープ範囲・点数を決めた根拠 (CFL, 物理的に意味のある下限上限)
- 振らないパラメータの fix 値とその理由
- 想定 core-hour と queue, 投入順序の判断
- 一度試して没にした設計 (e.g. 解像度を上げて 1 軸にした, 2 軸を諦めた)

```bash
runo notes append "Series A vti scan 設計" - <<'EOF'
独立軸: vti = 1, 3, 5, ..., 19 eV (10 点, 線形).
理由: 4σ CFL で 19 eV が上限, 1 eV が drift 主導側の下限.
固定: vflow=400 km/s, vte=10 eV, plate -34 V.
コスト: 10 run × 800 core × 8 h ≈ 64k core-h. gr20001a で OK.
EOF
```

## TOML フォーマット

詳細は `runops-reference` skill、`runo runs sweep --help`、または schemas を参照。
