# Goal contract

複数ファイル編集、高コスト操作、承認が必要な操作では、実行前に短い contract を示す。

```json
{
  "goal": "今回到達させる状態",
  "done": ["到達を示す evidence"],
  "budget": {"runs": 3, "wait_minutes": 10},
  "next": "最も近い一つの状態遷移",
  "commands": ["runo ..."]
}
```

checkpoint が必要な操作は contract を示して承認を得る。実行後は Done と evidence を
比較し、到達した時点で結果を返す。
