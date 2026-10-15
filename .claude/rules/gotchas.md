# Gotchas

## KUDPC の Lustre は RENAME_NOREPLACE に未対応

`/LARGE0`、`/LARGE1` では `renameat2(RENAME_NOREPLACE)` が EINVAL を返す。
`util.move_noreplace` は存在確認 + `rename` に落とす。`/tmp` 上のテストだけでは
この経路を通らないので、filesystem を触る変更は `--basetemp=/LARGE0/...` でも確認する。

## importlib.metadata のキャッシュ

`.venv` の dist-info 一覧は directory の mtime でキャッシュされる。Lustre の mtime は秒単位のため、
同じ秒に入れ替えた package を見落とす。`registry._entry_point` は探索前に
`importlib.invalidate_caches()` と `MetadataPathFinder.invalidate_caches()` を呼ぶ
（Python 3.10 では前者だけでは metadata のキャッシュが消えない）。`.pth`（editable install）を効かせるため
`sys.path.append` ではなく `site.addsitedir` を使う。

## project ローカル adapter の module 名

`adapters/X.py` は `runops_project_adapters.X` として読み込まれる。同じ process で別 project を
開くと `sys.modules` が上書きされる（テストでは問題にならないが、長寿命 process では注意）。

## typer の `standalone_mode=False`

`main()` は `app(..., standalone_mode=False)` で呼ぶため、`typer.Exit` は例外ではなく戻り値の
終了コードになる。`--version` の callback も同じ経路を通る。

## ログインノードでの実行

pytest は軽量なのでログインノードで実行してよい。simulator の build（`runo build`、
`local_source`）や他 repo の重いテストは、各 repo の規約に従い計算ノード（`tssrun`）で行う。

## v1 project を触るとき

実運用の v1 project（例: `~/large1/project_dust_release`）には `runo migrate-v1 --dry-run` だけを
実行する。適用は `work/`、`.venv`、`refs/`、`materials/` を除いたコピーで行う。v1 の
`.runops/work/<build>/src` は simulator repo の git worktree のことがある（migrate が
`git worktree repair` する）。
