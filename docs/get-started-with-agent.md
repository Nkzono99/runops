# AI エージェントではじめる runops

このページは、最初の project を作り、Agent に研究内容を渡すところまでのガイドです。
TOML schema や全 CLI command を覚える必要はありません。

## 1. 用意するもの

最初に次の情報があると、Agent が設計を始めやすくなります。

- 研究テーマと仮説
- 変えたい条件と観測したい量
- 使用する simulator
- 既存の base input や参考資料（あれば）
- 計算資源や期限の上限

base input が未定でも始められます。その場合は、未定であることと、Agent に比較して
ほしい候補を伝えてください。

## 2. Project を作る

新規 project:

```bash
uvx --from runops runo init
uvx --from runops runo doctor
uvx --from runops runo plugins --check
```

既存 project:

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
cd my-project
uvx --from runops runo doctor
uvx --from runops runo plugins --check
```

`runo init` は project 構造と Agent harness を生成します。`manifest.toml`、`input/`、
`submit/job.sh` などの生成物は直接編集せず、元になる case や survey を変更します。

### 推奨 plugin

simulator や site に対応する plugin がある場合、`runo init` と生成された harness に
推薦が表示されます。runops は plugin を自動 install しません。

- Codex: `$setup-plugins`
- Claude Code: `/setup-plugins`
- 推薦の再確認: `runo plugins`
- 機械可読な一覧: `runo plugins --json`

plugin の選択順や knowledge source との関係は
[Knowledge Layer](layers/knowledge.md) を参照してください。

## 3. Agent に依頼する

短い聞き取りから始める場合:

- Codex: `$setup-runops`
- Claude Code: `/setup-runops`

Agent が project context と環境を確認し、研究テーマ、simulator、base input、最初の
到達点を順に聞きます。

最初からまとめて伝えても構いません。

```text
月面平面に太陽風プラズマが入射するときの表面帯電を調べたい。
cases/emses/flat_surface/plasma.toml を base input にする。
主な独立変数は照射角、観測量は表面電位とシース厚。

まず project を確認し、campaign と pilot survey の案を作って。
run 数と概算 cost を示し、submit は確認するまで行わないで。
```

base input が未定なら、候補の比較も依頼に含めます。

```text
照射角と表面帯電の関係を調べたい。base input は未定。
利用可能な plugin、knowledge source、materials を確認し、候補と選定理由を示して。
```

## 4. 依頼に含めるとよい情報

Agent は依頼から Goal、Done、Budget、Invariant を組み立てます。特に Done と Budget を
明示すると、必要以上の作業や待機を避けられます。

| やりたいこと | 依頼例 |
|---|---|
| campaign を作る | `仮説、独立変数、観測量、単位、理由が揃ったら完了。` |
| survey を設計する | `pilot 点、run 数、概算 cost を dry-run で確認して。` |
| run を生成する | `created run ID、件数、由来を報告して。` |
| submit する | `対象と job ID の記録まで。初動待機はしない。` |
| 初動を確認する | `step が2回進むまで、最大10分確認して。` |
| 失敗を診断する | `log と failure reason を整理し、retry 方針を提案して。` |
| 比較図を作る | `図、source run、再現 command を残して。` |

再利用する変更は、run の生成済み input ではなく
`campaign.toml` → `case.toml` → `survey.toml` の適切な段階へ戻します。

## 5. 人が確認する操作

Agent 中心の運用でも、次の操作は確認を挟みます。

- 新しい survey の初回 bulk submit
- walltime、memory、node 数などを増やす retry
- `cancel`、`archive`、`purge-work`、`delete`
- 研究仮説や campaign の意味を変える編集
- migration と harness 更新

submit 前には、対象 run、queue、QOS、資源量、概算 cost を確認してください。

## 6. 完了 run を整理する

1 run を内容ごと退避する場合:

```bash
runo runs archive R2026...
runo runs list --include-archived
runo runs restore R2026...
```

survey の親を `survey.toml` や cancelled / failed run ごと退避する場合:

```bash
runo runs archive runs/scan --bundle
runo runs restore runs/_archive/scan --bundle
```

先に個別 archive した run がある場合は、採用対象を確認してから統合します。

```bash
runo runs archive runs/scan --bundle --adopt-archived
```

`--adopt-archived` が採用するのは、同じ親・同じ相対 path に由来する `archived` または
`purged` run だけです。競合や所有不明 file があれば、bundle 全体を変更せず拒否します。

`runs/_archive/` では manifest、入力パラメータ、解析 script を Git 管理できます。
`work/`、`status/`、cache / scratch は通常の run と同様に ignore されます。

## 7. 次に読む

- [Documentation](README.md) — 目的別の文書索引
- [Agent User Guide](agent-user-guide.md) — Agent の実行契約と保存先
- [Layer Docs](layers/README.md) — project state の責務分離
- [Interface Layer](layers/interface.md) — CLI、action、human gate
- [TOML リファレンス](toml-reference.md) — field を調べるとき

runops 自体への bug や改善案は、project 固有情報を除いた再現手順、期待する挙動、
実際の挙動、workaround をまとめてから upstream issue にします。
