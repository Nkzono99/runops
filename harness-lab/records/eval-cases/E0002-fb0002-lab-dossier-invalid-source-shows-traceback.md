---
id: E0002
record_type: eval_case
created_at: '2026-05-13T18:12:48+09:00'
status: active
capability: lab_cli_error_handling
failure_class: expected_user_error_traceback
source_feedback: FB0002
---

# E0002: FB0002-lab-dossier-invalid-source-shows-traceback を評価

## フィクスチャ

- source_feedback: `harness-lab/records/feedback/FB0002-lab-dossier-invalid-source-shows-traceback.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0002`
- observation: Running hops lab dossier --from RS0001 is an expected user mistake because research scans are adjacent lab records, but the command currently lets a ValueError escape as a rich traceback instead of returning a concise user-facing error.

## タスク

`lab_cli_error_handling` の `expected_user_error_traceback` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

In a HarnessOps lab with RS0001 present, run hops lab dossier --from RS0001; the command exits nonzero and prints a traceback ending with ValueError: dossier は FB/E/H/D レコードから作成してください: RS0001.

## 期待される挙動

The lab dossier command should catch unsupported source record types and print a short actionable message, preserving nonzero exit status without a traceback in normal operation.

## 合格基準

- `expected_user_error_traceback` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops eval --case E0002 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `expected_user_error_traceback` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
