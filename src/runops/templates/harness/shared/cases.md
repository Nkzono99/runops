# cases/ ディレクトリ

ここには simulation case の定義を置く。

## 構造

```
cases/<simulator>/<case-name>/
  case.toml          # パラメータ定義
  summarize.py       # run 後の解析フック
  <adapter-input>.toml  # adapter が使うベース入力 (simulator 依存)
  input/             # 追加入力ファイル (optional)
```

## ルール

- case は `runo case new <name> -s <simulator>` で生成する (cases/<sim>/ に自動生成)
- 生成された case.toml や入力テンプレートの編集は自由
- survey 付きは `runo case new <name> --survey` を使う
  - survey stub は `runs/<case_name>/survey.toml` に生成される
- case.toml の編集は自由だが、フォーマットは `runops-reference` スキルを参照
- テンプレートのパラメータは case.toml の `[params]` から展開される
