# アーキテクチャ（runops v2）

正本は `SPEC.md`。ここには実装時に守る境界だけを書く。

## 層

```text
cli.py  ──>  ops/*  ──>  config / project / manifest / case / runtime / jobgen / launchers / slurm / util
                    └─>  adapters/ (base, registry, generic)
```

- `cli.py`: 引数の解釈、確認 prompt、表示だけ。処理は `ops/` を呼ぶ。`RunopsError` の
  `exit_code`（1: 実行時エラー、2: 使い方・設定）を `main()` が終了コードにする。
- `ops/`: command ごとの処理。print / prompt をしない。Slurm を呼ぶ関数は `runner` 引数を取り、
  CLI は `slurm.default_runner` を呼び出し時に参照して渡す（テストは monkeypatch で差し替える）。
- 基盤 module は `ops/` と `cli.py` を import しない。`adapters/` は runops の他 module に依存しない
  （`base.py` は `util.load_toml` のみ）。
- `legacy_adapters/` は registry に登録しない。`ops/migrate.py` と `ops/setup.py` がファイルとして
  project にコピーするだけ。

## 不変条件

- run directory が主単位、`manifest.toml` が正本。書き込みは `Manifest.save()`（atomic）。
  `Manifest` は dict を保持し、知らない field を落とさない。
- run の発見は `runs/` 配下の走査。`.runops/index.toml` は捨ててよい cache。
- run の公開・移動は `util.move_noreplace`。`shutil.move` で別 filesystem へコピーしない。
- run id の採番と作成は `Project.id_lock()` の中で行い、staging は対象と同じ親 directory に置く。
- adapter の任意 hook は `registry.optional()` 経由で呼ぶ（Protocol を満たすだけの class も動く）。
- simulator 固有の知識（入力形式、完了判定、skill）を runops 本体に足さない。
