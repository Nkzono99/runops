# Example Prompt

Use the `python-package-refactor` skill to refactor this package safely.

Goal: split `src/acme_client/client.py` into smaller modules while preserving existing imports from `acme_client.client` and `acme_client`.

Constraints:

- No breaking public API changes.
- Do not add runtime dependencies.
- Keep CLI entry points unchanged.
- Run targeted tests first; run full pytest if feasible.

Expected output:

- Refactor plan.
- Implemented diff.
- API snapshot comparison.
- Verification summary with exact commands.
