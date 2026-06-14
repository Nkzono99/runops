---
name: setup-campaign
description: Set up campaign.toml from a research theme description. Use after runo init to define hypothesis, variables, and observables.
---

# campaign.toml をセットアップする

ユーザーから研究テーマの説明を受け取り、`campaign.toml` を構造化して記入する。

## 入力の収集

1. ユーザーの説明（自然言語）からテーマ・仮説・注目パラメータ・観測量を抽出する
2. 不明な点があれば質問して確認する（特に independent / fixed の区別）

## 参照すべき情報

```bash
# プロジェクトの現状を把握
uvx --from runops runo context --no-json

# 推奨 plugin と委譲 role を確認
uvx --from runops runo plugins --check
uvx --from runops runo plugins --json

# campaign.toml のスキーマ
uvx --from runops runo context --json

# 既存のケースがあれば参照
ls cases/
```

## campaign.toml の記入ルール

### [campaign] セクション

- `name`: プロジェクト名（既存値を維持）
- `description`: 研究の動機と背景を 1-3 文で記述
- `hypothesis`: 検証する仮説を具体的に記述（「〜すると〜になる」形式）
- `simulator`: 主シミュレータ名（既存値を維持）

### [variables] セクション

各パラメータに `role` を割り当てる:

| role | 意味 | 例 |
|------|------|----|
| `independent` | スイープで振るパラメータ | 照射角、速度 |
| `dependent` | シミュレーション結果として得られる量 | 表面電位 |
| `fixed` | 固定するパラメータ（理由を reason に記述） | グリッドサイズ |
| `controlled` | 条件間で揃える制御パラメータ | 初期温度 |

independent 変数には `range` または `values` を設定:

```toml
[variables.ray_zenith_angle_deg]
role = "independent"
values = [0, 20, 40, 60, 80]
unit = "deg"
reason = "太陽天頂角を変えて表面電位への影響を調べる"
```

### [observables] セクション

測定・解析する物理量を定義:

```toml
[observables.surface_potential]
source = "work/phisp*.h5"
description = "月面平面の表面電位分布"
unit = "V (normalized)"
```

## 出力

1. `campaign.toml` を更新する
2. 記入内容のサマリーを表示する
3. **`{{ skill_prefix }}note` で経緯を残す** (下記参照)
4. 次のステップを提案する:
   - ケースが未作成なら `runo case new <case_name> -s <simulator>` を提案 (cases/<sim>/ に自動生成)
   - ケースが既存なら survey 設計を提案

## `{{ skill_prefix }}note` で残すべきこと

campaign 設計の意思決定は raw な状態で `notes/YYYY-MM-DD.md` に残しておく
(後の `{{ skill_prefix }}learn` の素材になる):

- どのテーマ・仮説を採用したか、なぜか
- 却下した代替仮説 (一度考えてやめたもの)
- independent / fixed / controlled の境界をどう判断したか
- スコープを絞った理由 (時間・資源・物理的妥当性)
- ユーザーとの議論で出た論点 (言われたまま採用したのはどれか, 反対したのはどれか)

例:

```bash
uvx --from runops runo notes append "campaign セットアップ" - <<'EOF'
Theme: thermal-motion-induced ion depletion (2D PIC).
Hypothesis: vti が大きいほど plate 下流の枯渇角 alpha が広がる。

independent: vti (1-19 eV, CFL 4σ で 19 eV が上限).
fixed: vflow=400 km/s, dx=0.5 m, box 4000x800.
没案: vflow も振る → 2 軸スキャンは 30 run × 2 で資源が足りない。
EOF
```

## 注意

- 既存の `campaign.toml` の `name` と `simulator` は上書きしない（ユーザーが明示的に変更を指示した場合を除く）
- パラメータ名・物理的意味・観測量の設計は simulator/environment plugin、
  `.runops/knowledge/enabled/imports.md`、project materials を優先する
- adapter の agent guide は runops 側の最小 fallback であり、完全な simulator manual
  として扱わない
- 物理単位は必ず `unit` に記入する
- `reason` は将来の自分や共同研究者が読んで意図がわかるように書く
