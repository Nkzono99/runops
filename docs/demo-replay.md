# Demo Replay

`runo demo` は、Codex session log や正規化済み demo events JSONL から、
研究室向けの説明・録画に使える replay UI を生成するための補助機能です。

## 目的

通常の画面録画だけだと、次の点が伝わりにくくなります。

- どのファイルを読んだか
- どのファイルを作成・更新したか
- どのコマンドを実行したか
- どの順番で作業が進んだか

`runo demo` ではこれらを時系列イベントに落とし、HTML として再生できる形にします。

## 最短手順

Codex session log から replay HTML を一気に作るには、次の 1 コマンドで十分です。

```bash
uvx --from runops runo demo build-codex-replay \
  ~/.codex/sessions/2026/04/24/rollout-....jsonl \
  --out replay.html \
  --workspace-root . \
  --title "RunOps Session Replay"
```

session log を毎回手で指定したくない場合は、`build-codex-replay` の
第 1 引数を省略できます。この場合、`--workspace-root` に一致する
最新の Codex session を `~/.codex/sessions` から自動探索します。

```bash
uvx --from runops runo demo build-codex-replay \
  --out replay.html \
  --workspace-root . \
  --title "RunOps Session Replay"
```

`CODEX_HOME` を独自に切っている場合はその配下の `sessions/` を使います。
探索先を明示したい場合は `--sessions-root` で上書きできます。

このコマンドは内部で次の 2 段階を実行します。

1. session log を `demo-events.jsonl` に正規化する
2. replay UI を self-contained な `replay.html` にレンダリングする

中間の JSONL も残したい場合は `--events-out` を指定します。

```bash
uvx --from runops runo demo build-codex-replay \
  ~/.codex/sessions/2026/04/24/rollout-....jsonl \
  --events-out demo-events.jsonl \
  --out replay.html \
  --workspace-root .
```

自動探索と `--events-out` を併用することもできます。

```bash
uvx --from runops runo demo build-codex-replay \
  --events-out demo-events.jsonl \
  --out replay.html \
  --workspace-root . \
  --sessions-root ~/.codex/sessions
```

## 2 段階で実行する場合

中間生成物を確認しながら進めたい場合は、import と render を分けて使えます。

```bash
uvx --from runops runo demo import-codex-session \
  ~/.codex/sessions/2026/04/24/rollout-....jsonl \
  --out demo-events.jsonl \
  --workspace-root .

uvx --from runops runo demo render-replay \
  demo-events.jsonl \
  --out replay.html \
  --title "Survey Demo Replay" \
  --subtitle "Imported from Codex session log"
```

## 現在の replay UI に含まれるもの

- chapter ナビゲーション
- current chapter の prompt 表示
- 触れたファイルのツリー表示
- 現在イベントの summary / path / metadata
- command / diff / output / context の個別表示
- activity feed
- timeline と再生コントロール

chapter は event の型遷移や主要 command / 主要ファイル更新から自動推定します。
完全に意味論的な章分けではありませんが、デモ説明には十分使える粒度を狙っています。

## 取り込める情報

Codex session log importer は主に次を拾います。

- `session_meta`
- `user_message`
- `agent_message`
- `exec_command_end`
- `parsed_cmd` 由来の `read` / `search` / `list_files`
- `patch_apply_end`
- `mcp_tool_call_end`
- `task_start` / `task_complete`

`reasoning` や巨大な developer prompt dump は replay には不要なので取り込みません。

## 録画のすすめ方

HTML を作ったあとは、ブラウザで `replay.html` を開いて録画します。

- 手動録画: OBS でブラウザ画面を録画
- 自動録画: Playwright やブラウザの screen capture を使って再生を収録

研究室向けの説明では、等速再生よりも次のような構成が見やすいです。

- 0:00 要求の確認
- 0:10 既存 case / campaign の確認
- 0:20 survey の更新
- 0:35 `runo runs sweep`
- 0:50 manifest / job script の確認
- 1:05 wrap-up

## 運用上の注意

- session log には絶対パスやユーザー名が入りうるので、公開前に確認する
- 機密の project 名やサーバ名が summary に出る場合は、session log 側または replay HTML 側でマスクする
- runops 側の `--event-log` は将来の統合・補助用途には有用だが、現時点の built-in importer は Codex session log を主対象としている

## 今後の拡張候補

- manual chapter file の読み込み
- replay UI からイベント種別の filter
- runops event log と session log の merge
- Playwright を使った自動動画書き出し
