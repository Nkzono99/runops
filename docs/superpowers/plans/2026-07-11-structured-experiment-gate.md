# Structured Experiment Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce structured pilot/full survey gates and Research Director candidate comparison.

**Architecture:** Parse survey research metadata and a project experiment ledger in an application service, call it before bulk plan construction, and update generated harness guidance/scaffold.

**Tech Stack:** Python 3.10+, TOML, frozen dataclasses, Typer, pytest.

**Status:** active

### Task 1: Contract and parser

- [ ] Add failing unit tests for pilot/full, candidates, paths, and decisions.
- [ ] Implement `application/research/experiments.py` typed parser and validator.
- [ ] Run focused tests and commit `feat: add structured experiment gate`.

### Task 2: Bulk submission integration

- [ ] Add failing CLI tests for fail-closed survey bulk, dry-run, `--yes`, and generic compatibility.
- [ ] Invoke the validator before run discovery/plan construction.
- [ ] Run submit tests and commit `feat: gate survey bulk submission`.

### Task 3: Generated harness and migration

- [ ] Add failing scaffold/harness assertions.
- [ ] Add `research/experiments.toml`, update Research Director/review-pilot/run-all guidance, builder/update expectations, SPEC, commands, and v0 migration note.
- [ ] Run harness/init/update tests and commit `docs: structure experiment gate workflow`.

### Task 4: Verification

- [ ] Run Ruff format/check, mypy, full pytest and branch coverage policy.
- [ ] Run CLI smoke checks.
- [ ] Mark this plan completed with an Outcome and commit closeout changes.
