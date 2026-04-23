# 実行前ルール

複数ファイル編集または高コスト操作の前には、短い plan を出す。

```json
{
  "goal": "what you want to achieve",
  "edits": ["file1.toml", "file2.toml"],
  "commands": ["runo runs sweep ...", "runo runs submit --all ..."],
  "checkpoints": ["Confirm survey size before bulk submit"]
}
```

- 高コスト操作では run 数・queue・retry 理由を書く
- plan にない高コスト操作をいきなり実行しない
- approval が必要な操作は、plan を出したところで止まる

