---
id: H0002
record_type: hypothesis
created_at: '2026-05-13T18:13:06+09:00'
status: proposed
target_capability: lab_cli_error_handling
source_eval_case: E0002
---

# H0002: E0002-fb0002-lab-dossier-invalid-source-shows-traceback の仮説

## 仮説

Catching expected domain ValueError exceptions in lab dossier will make HarnessOps lab CLI safer for agents and humans by turning invalid source records into actionable messages instead of tracebacks.

## メカニズム

Wrap create_or_update_improvement_dossier in the lab dossier command with ValueError handling, echo the domain message, suggest valid source record prefixes FB/E/H/D or the correct research-scan path, and exit with code 1.

## 最小実装

Add a ValueError except block around create_or_update_improvement_dossier in harnessops.cli.lab.dossier and add a CliRunner test that hops lab dossier --from RS0001 exits 1, includes the concise message, and omits Traceback.

## 代替案: 削除または統合

Keep core records.py unchanged and rely on agents to know valid prefixes, but this leaves expected mistakes noisy and harder to recover from.

## 期待される利点

Normal invalid input becomes readable, testable, and consistent with existing eval/feedback CLI error handling.

## 想定される欠点

Catching broad ValueError in this command could hide an internal bug if the message is not domain-specific; the handler should remain narrow or use a domain exception later.

## 評価計画

Create a fixture with an RS record, run lab dossier against it, and assert nonzero exit, no traceback, and a message explaining supported source record types.

## 中止基準

Reject if the fix suppresses unexpected internal exceptions or makes debugging real corruption harder.
