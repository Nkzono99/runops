# Research Layer

`research/` は、生成 project 側に置く **研究判断の隔離層** です。
runops 本体の実装状態や Agent の手順ではなく、現在の研究判断を人間と Agent が
同じ地点から再開するための台帳として使います。

## 目的

`research/agenda.md` は TODO リストではありません。次を短く残す mutable な
decision ledger です。

- 今、何を信じているか
- その根拠はどこにあるか
- 何が未解決か
- なぜ次にそれをやるのか
- 何が出たら判断を変えるのか
- 何を今はやらないのか

本文は日本語で書きます。コード、コマンド、変数名、run_id、ファイルパス、
エラーメッセージは実際の表記のまま残します。

## 生成される構成

```text
research/
  README.md
  agenda.md
  paper_requests.toml
  proposals/
    .gitkeep
  reviews/
    .gitkeep
```

`runo init` はこの構成を作ります。既存 project では `runo update-harness` が、
不足している `research/` scaffold だけを補完します。

## paper request contract

paper draft から出た追加解析・図表・追加実験・export 要望は
`research/paper_requests.toml` に structured queue として置けます。これは
実行キューではなく、paper 側の文脈を `research/agenda.md` や
`research/proposals/` へ戻すための handoff です。

詳細な schema と例は [Paper Request Contract](../paper-requests.md) を参照します。
MCP では `runops.paper.request.draft`, `runops.paper.requests.list`,
`runops.paper.request.plan` が read / plan 入口を提供します。paperops など外部の
paper tool は draft tool で request 候補を preview / validation してから、人間の
確認後に `paper_requests.toml` へ追記します。追加実験の run creation / survey
expansion / submit は明示操作に残します。

## context 入口

`runo context --json` は、Agent が最初に読む project context に
`research_agenda` を含めます。agenda 全文ではなく、存在、path、template 判定、
現在判断の preview、active question 数、next action 数、paused/killed 数だけを
返します。

初期 template の空欄は count しません。Agent は `research_agenda.exists` が true
なら、next action を提案する前に `research/agenda.md` を直接読みます。

## レイヤー分離

| 場所 | 役割 | 更新方針 |
|------|------|----------|
| `campaign.toml` | 研究目的・仮説・変数・観測量 | 研究憲章として慎重に編集 |
| `notes/YYYY-MM-DD.md` | 日次 lab notebook | append-only |
| `notes/reports/` | 整理済み long-form report | 改稿可 |
| `research/agenda.md` | 現在の研究判断 | mutable |
| `research/paper_requests.toml` | paper draft から戻る解析・図表・実験要望 | structured queue |
| `research/proposals/` | 実行前の重い判断 | 必要時に新規作成 |
| `research/reviews/` | 過去判断の snapshot | checkpoint ごとに新規作成 |
| `.agents/skills/`, `.claude/skills/` | Agent の手順 | harness template から生成 |

## proposal / review

普段は `agenda.md` だけで回します。次の場合だけ `proposals/` や `reviews/` を
使います。

`proposals/` を作る目安:

- production sweep
- 新しい physical model family
- 高コストな rerun
- campaign-level assumption の変更
- report / paper レベルの主張

`reviews/` を作る目安:

- 主要 result が出た
- failed / surprising run が出た
- 同じ story が 3 件以上の note に分散した
- pivot / pause / kill を決めた

## Scientific execution gate

production / large survey は、計算資源の一括投入前に次の state machine を通します。

```text
agenda active question
  -> proposal + bounded pilot
  -> pilot execution
  -> evidence review
  -> EXPAND | REVISE | STOP | WAIT
  -> full submit (EXPAND only)
```

`research-director` は active question から 1 件の bounded experiment を選び、
`research/proposals/<date>-<topic>.md` に仮説、反証条件、pilot matrix、required
artifact、cost ceiling、stop / expand criterion を事前登録します。agenda の
`Active Experiment Portfolio` は proposal、pilot run_id、review path、decision を
結びます。

pilot 完了後は `review-pilot` が事前基準と実 artifact を照合し、
`research/reviews/<date>-<topic>.md` に `EXPAND`, `REVISE`, `STOP`, `WAIT` のいずれかを
記録します。review と portfolio が `EXPAND` で一致するときだけ `run-all` が
`runo runs submit --dry-run --all` と full submit へ進みます。`--yes` は CLI prompt
だけを省略し、この scientific gate は省略しません。

## Agent skill

project 側には `research-agenda`, `research-director`, `review-pilot` skill が
展開されます。Claude Code では `/research-director`、Codex では
`$research-director` のように呼びます。

この skill は `campaign.toml`、`research/agenda.md`、最近の `notes/`、
関連 run の manifest / summary / figure を必要範囲で読み、`agenda.md` に
現在の見立て、active question、current decision、判断が変わる条件、
next action、paused/killed、runops への feedback 候補を反映します。
