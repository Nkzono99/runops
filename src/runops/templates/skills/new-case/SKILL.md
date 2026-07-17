---
name: new-case
description: Use when the requested outcome is one validated simulator case generated from a research intent or base input.
---

# 研究意図を再利用可能なcaseにする

## 実行契約

- **Goal**: 指定simulatorのbase inputと固定parameterを一つのcaseとして定着させる
- **Done**: case path、source、変更parameterと理由、検証結果を報告できる
- **Budget**: 一つのcase。未解決のparameter gapごとに最も近いsourceだけを読む
- **Invariant**: `runo case new`で生成し、immutable parameterを守り、run生成へ自動で進まない

## Source routing

| information gap | source |
|---|---|
| 研究目的・固定量 | `campaign.toml`, `research/CURRENT.md` |
| parameter名・物理範囲 | simulator plugin skill / enabled knowledge |
| project既知constraint | `.runops/facts.toml` |
| base input例 | 指定input、`materials/`、最後に`refs/` cookbook |

## Case routing

```bash
runo case new <name> -s <simulator>
runo case new <name> -s <simulator> --survey
runo case new <name> -s <simulator> -d <dest>
```

`--survey`はsurvey雛形も今回のDoneに含まれる場合だけ使う。生成後は
`cases/<simulator>/<case>/case.toml`とsimulator inputを対象にする。

- base inputには共通設定、`case.toml [params]`にはcase固有overrideを置く
- `[case]`にはsimulator、launcher、研究意図が分かるdescriptionを持たせる
- sensitive parameterは理由と安全範囲を残す
- source、変更値、validation evidenceを確認してDoneを返す

survey設計、run生成、journal追記はそれぞれ別Goalとして扱う。
