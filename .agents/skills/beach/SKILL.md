---
name: beach
description: "Use when working with the BEACH (BEM + Accumulated CHarge) simulator in runops: generating or editing beach.toml, creating runs, checking BEACH outputs, analyzing CSV results, or producing BEACH visualizations."
---

あなたは BEACH (BEM + Accumulated CHarge) シミュレータの専門エージェントです。
境界要素法による表面帯電シミュレーションの実行管理、データ処理、可視化を担当します。

## BEACH について

- **リポジトリ**: https://github.com/Nkzono99/BEACH
- **種類**: 境界要素法 (BEM) による表面帯電シミュレーション
- **言語**: Fortran (コア) + Python (ライブラリ・後処理)
- **インストール**: `pip install beach-bem`
- **入力**: TOML 形式 (`beach.toml`)
- **出力**: CSV ファイル (charges.csv, mesh_triangles.csv 等)
- **実行**: `beach beach.toml` または `mpirun -np N beach beach.toml`
- **後処理ツール**: `beachx` コマンド群

## 入力ファイル (beach.toml)

TOML 形式の設定ファイル。主要セクション：

```toml
[sim]
dt = 1.4e-8
batch_count = 10
max_step = 500
field_solver = "default"
box_origin = [0.0, 0.0, 0.0]
box_size = [1.0, 1.0, 1.0]

[[particles.species]]
name = "electron"
q_particle = -1.602e-19
m_particle = 9.109e-31
temperature_ev = 1.0
source_mode = "reservoir_face"

[[particles.species]]
name = "ion"
q_particle = 1.602e-19
m_particle = 9.109e-28
temperature_ev = 0.1
source_mode = "reservoir_face"

[mesh]
mode = "template"
template = "sphere"
radius = 0.1
center = [0.5, 0.5, 0.5]

[output]
dir = "outputs/latest"
history_stride = 10
write_potential_history = true
```

### CLI ワークフロー
```bash
beachx config init          # case.toml をプリセットから生成
beachx config validate      # 設定の検証
beachx config render        # case.toml → beach.toml の変換
beach beach.toml            # シミュレーション実行
```

## HPC 環境

- Python venv の activate が必要: `source /path/to/venv/bin/activate`
- venv 自動検出: `resolve_runtime` が cwd から上位ディレクトリを辿って `.venv` を自動検出。`simulators.toml` の `venv_path` が未設定でも動作する
- module load は不要 (Python パッケージとして完結)
- MPI 並列対応: `mpirun -np N beach beach.toml` or `srun beach beach.toml`

### 典型的な job.sh
```bash
#!/bin/bash
#SBATCH -p gr10451a
#SBATCH --rsc p=4:t=1:c=1
#SBATCH -t 24:00:00

source /path/to/venv/bin/activate

cd work/
beach beach.toml

# Post-processing
beachx inspect outputs/latest --save-mesh mesh.png
beachx coulomb outputs/latest --component z --save coulomb_z.png
```

## 実行管理タスク

### 入力ファイル生成
- beach.toml の生成・編集
- パラメータの検証
- メッシュ設定の構成

### ジョブ投入
- job.sh 生成 (venv activation 付き)
- MPI プロセス数の設定

### 状態監視
- summary.txt の確認
- 出力 CSV ファイルの存在チェック
- エラー検出

## データ処理タスク

### 出力ファイル
- `summary.txt`: 実行サマリ
- `charges.csv`: メッシュ要素ごとの電荷分布
- `mesh_triangles.csv`: メッシュ形状定義（三角形要素）
- `charge_history.csv`: 電荷の時間発展
- `potential_history.csv`: 電位の時間発展

### Python API による読み込み
```python
from beach import Beach

# 結果の読み込み
b = Beach("outputs/latest")
result = b.result

# 電荷データ
import pandas as pd
charges = pd.read_csv("outputs/latest/charges.csv")
mesh = pd.read_csv("outputs/latest/mesh_triangles.csv")
```

### CSV 直接読み込み
```python
import pandas as pd
import numpy as np

# 電荷分布
charges = pd.read_csv("work/outputs/latest/charges.csv")
print(f"Total charge: {charges['charge'].sum():.6e} C")
print(f"Max charge density: {charges['charge'].max():.6e} C")

# 時間発展
history = pd.read_csv("work/outputs/latest/charge_history.csv")
```

## 可視化タスク

### beachx コマンドによる可視化
```bash
# メッシュと電荷分布の可視化
beachx inspect outputs/latest --save-mesh analysis/figures/mesh.png

# アニメーション生成
beachx animate outputs/latest --quantity potential --save-gif analysis/figures/potential.gif

# クーロン力の可視化
beachx coulomb outputs/latest --component z --save analysis/figures/coulomb_z.png

# 移動度解析
beachx mobility outputs/latest --density-kg-m3 2500 --mu-static 0.4
```

### Python による可視化
```python
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# 電荷の時間発展
history = pd.read_csv("work/outputs/latest/charge_history.csv")
plt.figure(figsize=(10, 6))
plt.plot(history["step"], history["total_charge"])
plt.xlabel("Step")
plt.ylabel("Total Charge (C)")
plt.title("Charge Accumulation Over Time")
plt.grid(True)
plt.savefig("analysis/figures/charge_history.png", dpi=150, bbox_inches="tight")

# 電荷分布のヒートマップ
charges = pd.read_csv("work/outputs/latest/charges.csv")
mesh = pd.read_csv("work/outputs/latest/mesh_triangles.csv")
# 三角形メッシュ上の電荷分布を matplotlib.tri で可視化
from matplotlib.tri import Triangulation
# ... (メッシュデータに応じて構成)
```

### 注意事項
- BEACH の Python API (`from beach import Beach`) を使うには `beach-bem` パッケージが必要
- `beachx` コマンドは BEACH インストール時に一緒にインストールされる
- venv 環境の activate を忘れずに
- 解析結果は `analysis/` ディレクトリに保存
- 図は `analysis/figures/` に保存

## コマンド実行時の注意

- BEACH の Python 環境は venv で管理されている
- プロジェクトルート付近に venv がある想定
- `source venv/bin/activate` してから Python/beachx コマンドを実行
- 大量のメッシュデータの処理はメモリに注意
