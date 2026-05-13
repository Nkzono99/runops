"""Claude Code harness policy and settings generation."""

from __future__ import annotations

import json
from typing import Final

_CLI_COMMANDS: Final[tuple[str, ...]] = (
    "uvx --from runops runo",
    "runo",
    "runops",
)


def _cli_bash_patterns(*patterns: str) -> tuple[str, ...]:
    """Expand runops CLI command suffixes for preferred and legacy names."""
    return tuple(
        f"Bash({command} {pattern})"
        for command in _CLI_COMMANDS
        for pattern in patterns
    )


# Bash commands the agent can run without confirmation.
#
# We deliberately keep ASK_BASH small (see _ASK_BASH below): the only Bash
# commands that should prompt are ones that spend HPC resources or destroy
# files irreversibly.  Everything else, including knowledge sync, ref
# updates, and local git commits, lives here.
_ALLOW_BASH: Final[tuple[str, ...]] = (
    # Read-only inspection
    *_cli_bash_patterns(
        "--help*",
        "--version*",
        "context*",
        "runs list*",
        "runs status*",
        "runs sync*",
        "runs jobs*",
        "runs dashboard*",
        "runs history*",
        "runs log*",
        "doctor*",
        "config show*",
    ),
    # Generation (cheap, reversible by deleting the new files)
    *_cli_bash_patterns(
        "case new *",
        "runs create *",
        "runs sweep *",
        "runs clone *",
        "runs extend *",
    ),
    # Analysis (read + write into analysis/)
    *_cli_bash_patterns(
        "analyze summarize*",
        "analyze collect*",
        "analyze plot*",
        "analyze export*",
    ),
    # Knowledge management (mutates .runops/knowledge/ via runops, reversible)
    *_cli_bash_patterns(
        "knowledge list*",
        "knowledge show*",
        "knowledge facts*",
        "knowledge save*",
        "knowledge add-fact*",
        "knowledge promote-fact*",
        "knowledge source list*",
        "knowledge source status*",
        "knowledge source attach*",
        "knowledge source detach*",
        "knowledge source sync*",
        "knowledge source render*",
    ),
    # Notes (lab notebook, append-only by design)
    *_cli_bash_patterns(
        "notes append*",
        "notes list*",
        "notes show*",
    ),
    # Slurm submission is non-destructive but spends queue/HPC resources.
    # Allow it at the permission layer; workflow rules require dry-run review
    # and explicit chat confirmation before real submission.
    *_cli_bash_patterns(
        "runs submit*",
    ),
    # Refs / config additions (mutates the corresponding TOML, which is
    # itself ask-listed below — the resulting prompt happens once, not twice)
    *_cli_bash_patterns(
        "update-harness*",
        "update-refs*",
        "config add-simulator*",
        "config add-launcher*",
    ),
    # Lifecycle move that does not delete data
    *_cli_bash_patterns(
        "runs archive*",
        "runs cancel*",
    ),
    # Dev tooling
    "Bash(uv run pytest*)",
    "Bash(uv run ruff*)",
    "Bash(uv run mypy*)",
    "Bash(source .venv/bin/activate*)",
    "Bash(cat runs/*/work/*.out*)",
    "Bash(cat runs/*/work/*.err*)",
    # Git: read-only and local commits.  Pushes are not auto-allowed; the
    # agent system prompt already says to only commit when explicitly asked.
    "Bash(git status*)",
    "Bash(git log*)",
    "Bash(git diff*)",
    "Bash(git commit*)",
)
# Bash commands that must always prompt the user.  Keep this list as short
# as possible — every entry here trains the user to dismiss prompts.
_ASK_BASH: Final[tuple[str, ...]] = (
    *_cli_bash_patterns(
        "runs purge-work*",  # deletes work/ files irreversibly
        "runs delete*",  # removes run directory irreversibly
    ),
)
_DENY_BASH: Final[tuple[str, ...]] = (
    "Bash(rm -rf *)",
    "Bash(git push --force*)",
    "Bash(git reset --hard*)",
)
# Paths the agent may freely Edit/Write without confirmation.
# .claude/{rules,skills,commands}/** and .agents/skills/** are allowed because
# they are documentation-style files.  Actual policy files
# (.claude/settings.json, .claude/hooks/**, .codex/config.toml,
# .codex/rules/**) require confirmation.
_ALLOW_EDIT_PATHS: Final[tuple[str, ...]] = (
    "/campaign.toml",
    "/cases/**",
    "/surveys/**",
    "/runs/**/survey.toml",
    "/docs/**",
    "/notes/**",
    "/README.md",
    "/.claude/rules/**",
    "/.claude/skills/**",
    "/.claude/commands/**",
    "/.agents/skills/**",
    "/.codex/README.md",
    "/.vscode/**",
    "/.idea/**",
)
# Edit/Write paths that always prompt.  Limited to project-defining and
# agent-behaviour-defining files.
_ASK_EDIT_PATHS: Final[tuple[str, ...]] = (
    "/runops.toml",
    "/simulators.toml",
    "/launchers.toml",
    "/CLAUDE.md",
    "/AGENTS.md",
    "/**/CLAUDE.md",
    "/**/AGENTS.md",
    "/.claude/settings.json",
    "/.claude/settings.local.json",
    "/.claude/hooks/**",
    "/.codex/config.toml",
    "/.codex/rules/**",
)
_DENY_EDIT_PATHS: Final[tuple[str, ...]] = (
    "/SITE.md",
    "/runs/**/manifest.toml",
    "/runs/**/input/**",
    "/runs/**/submit/**",
    "/runs/**/work/**",
    "/runs/**/status/**",
    "/runs/**/analysis/**",
    "/.runops/environment.toml",
    "/.runops/knowledge/**",
    "/.runops/insights/**",
    "/.runops/facts.toml",
    "/refs/**",
    "/.venv/**",
    "/.git/**",
)
_DENY_READ_PATHS: Final[tuple[str, ...]] = (
    "/.env",
    "/.env.*",
    "/secrets/**",
    "~/.ssh/**",
    "~/.aws/credentials",
    "~/.config/gcloud/**",
    "~/.kube/config",
)


def _build_permission_rules(
    tools: tuple[str, ...],
    patterns: tuple[str, ...],
) -> list[str]:
    """Expand tool/path combinations into Claude permission rule strings."""
    rules: list[str] = []
    for tool in tools:
        rules.extend(f"{tool}({pattern})" for pattern in patterns)
    return rules


def build_claude_settings() -> str:
    """Build team-shared Claude Code settings for runops projects.

    The returned settings declare allow / ask / deny rules only.  Behavioural
    expectations that earlier versions enforced via PreToolUse hooks (submit
    approval, run-directory protection, Bash write guards) are now documented
    in ``.claude/rules/runops-workflow.md`` so they remain visible to the
    agent without forcing per-action shell hooks on the user.
    """
    allow_rules = list(_ALLOW_BASH)
    allow_rules.extend(_build_permission_rules(("Edit", "Write"), _ALLOW_EDIT_PATHS))

    ask_rules = list(_ASK_BASH)
    ask_rules.extend(_build_permission_rules(("Edit", "Write"), _ASK_EDIT_PATHS))

    deny_rules = list(_DENY_BASH)
    deny_rules.extend(_build_permission_rules(("Edit", "Write"), _DENY_EDIT_PATHS))
    deny_rules.extend(_build_permission_rules(("Read",), _DENY_READ_PATHS))

    settings = {
        "permissions": {
            "allow": allow_rules,
            "ask": ask_rules,
            "deny": deny_rules,
            "disableBypassPermissionsMode": "disable",
        },
    }
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
