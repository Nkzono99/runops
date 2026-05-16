---
id: H0012
record_type: hypothesis
created_at: '2026-05-17T04:10:35+09:00'
status: proposed
target_capability: unclassified
source_eval_case: E0012
---

# H0012: E0012-fb0012-hops-update-harness-gitignore-whitespace の仮説

## 仮説

Preserving existing file line endings and skipping normalized no-op writes will remove update-harness whitespace churn.

## メカニズム

Compare managed output against existing files after normalization, preserve detected newline style when writing, and trim template trailing whitespace before emission.

## 最小実装

Add normalized content comparison and newline-style preservation to update-harness writes, surface unchanged status in summaries, and run diff-check validation in tests.

## 代替案: 削除または統合

Accept line-ending-only diffs and rely on humans to trim whitespace, which obscures real managed artifact changes.

## 期待される利点

Harness updates become smaller, easier to review, and less likely to fail git diff --check for generated artifacts.

## 想定される欠点

Normalization rules must not hide intentional whitespace-sensitive changes in managed files.

## 評価計画

Create fixtures with LF and CRLF .gitignore files plus template trailing spaces; assert no diff on equivalent content and no diff-check violations after update.

## 中止基準

Reject if the writer silently rewrites user-managed files or suppresses real content differences.
