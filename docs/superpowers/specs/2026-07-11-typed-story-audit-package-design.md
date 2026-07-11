# Typed Story Audit Package Design

**Status:** approved
**Date:** 2026-07-11

## Purpose

Replace the monolithic `application/analysis/story.py` implementation with a
typed `application/analysis/story/` package. The refactor isolates untyped
TOML/artifact input at the package boundary, gives schema, source collection,
acceptance decisions, rendering, and workspace orchestration separate owners,
and preserves the current CLI, public Python imports, files, diagnostics, and
audit semantics.

This is a behavior-preserving refactor. Story schema version 1 remains the only
supported format and no project-state migration is introduced.

## Package structure

```text
src/runops/application/analysis/story/
  __init__.py    # compatibility facade and public exports
  models.py      # immutable typed records and serialization boundaries
  schema.py      # story.toml parsing and validation
  sources.py     # source-kind detection and artifact collection
  audit.py       # selector matching and acceptance decisions
  render.py      # audit.json payload and audit.md rendering
  workspace.py   # create/audit filesystem orchestration
```

The existing `src/runops/application/analysis/story.py` is removed once the
package facade exposes the same public names. No compatibility shim file is
kept because a module and package with the same import name would be ambiguous.

## Public compatibility boundary

These imports and signatures remain valid:

```python
from runops.application.analysis import (
    StoryAuditResult,
    StoryWorkspaceResult,
    audit_story_workspace,
    create_story_workspace,
    slugify_story_id,
)
```

`runops.application.analysis.story` re-exports the same five symbols.
`StoryAuditResult.steps` remains `list[dict[str, Any]]` and `warnings` remains
`list[str]` at the public boundary so existing clients and tests do not need a
migration. Internally, orchestration converts typed records to these legacy
containers only when constructing the public result.

The following observable behavior remains byte-for-byte or value-for-value
compatible:

- generated `story.toml` keys and defaults;
- `audit.json` keys, omitted optional artifact keys, sorted-key formatting, and
  trailing newline;
- `audit.md` headings, ordering, evidence labels, and trailing newline;
- current `SimctlError` messages for invalid stories and source mismatches;
- project-root-relative source resolution and stable story-id generation;
- blocked, missing, partial, and covered precedence.

## Typed domain records

`models.py` defines frozen dataclasses and narrow literal aliases:

```python
SourceKind = Literal["run", "survey", "comparison", "path"]
StepStatus = Literal["blocked", "missing", "partial", "covered"]
OverallStatus = Literal["blocked", "missing", "partial", "covered"]

@dataclass(frozen=True)
class StorySource:
    kind: SourceKind
    path: str

@dataclass(frozen=True)
class StoryStep:
    id: str
    title: str
    required_artifacts: tuple[str, ...]
    acceptable_status: tuple[str, ...]
    claim_ceiling: str = ""
    notes: str = ""

@dataclass(frozen=True)
class StorySpec:
    schema_version: int
    id: str
    title: str
    status: str
    sources: tuple[StorySource, ...]
    steps: tuple[StoryStep, ...]

@dataclass(frozen=True)
class ArtifactRecord:
    kind: str = ""
    path: str = ""
    title: str = ""
    description: str = ""
    status: str = "draft"
    source_scope: str = ""
    source_index: str = ""
    run_id: str = ""
    quantity: str = ""
    name: str = ""
    artifact_id: str = ""
    tags: tuple[str, ...] = ()
    present_fields: frozenset[str] = frozenset()

@dataclass(frozen=True)
class ArtifactEvidence:
    selector: str
    artifact: ArtifactRecord

@dataclass(frozen=True)
class StepAudit:
    id: str
    title: str
    status: StepStatus
    required_artifacts: tuple[str, ...]
    acceptable_status: tuple[str, ...]
    matched_artifacts: tuple[ArtifactEvidence, ...]
    weak_artifacts: tuple[ArtifactEvidence, ...]
    missing_artifacts: tuple[str, ...]
    claim_ceiling: str = ""
    notes: str = ""

@dataclass(frozen=True)
class StoryAudit:
    spec: StorySpec
    generated_at: str
    story_path: str
    overall_status: OverallStatus
    warnings: tuple[str, ...]
    steps: tuple[StepAudit, ...]
```

`present_fields` preserves the current JSON omission behavior for artifact
summaries while allowing matching and audit logic to use attributes instead of
`dict[str, Any]`. Each record owns a deterministic `to_dict()` method only when
it crosses a JSON/TOML/public-result boundary.

## Processing stages

### Schema stage

`schema.py` reads TOML and returns `StorySpec`. Raw `dict[str, object]` values
exist only while parsing. Validation keeps the existing rules: schema version
must be the integer `1`, source kinds are exact lowercase values, steps are
non-empty and uniquely identified, and required/acceptable arrays contain at
least one non-empty string.

### Source stage

`sources.py` accepts `StorySource` and returns:

```python
@dataclass(frozen=True)
class SourceCollection:
    artifacts: tuple[ArtifactRecord, ...]
    warnings: tuple[str, ...]
```

It owns source path resolution, kind detection, run/survey/comparison/path
artifact discovery, and normalization from external artifact mappings into
`ArtifactRecord`. A missing source remains a warning; the workspace layer
derives `source_blocked` when any warning begins with the established missing
source prefix.

### Audit stage

`audit.py` is filesystem-free. It accepts typed steps and artifacts and returns
`StepAudit` plus the typed overall status. Selector parsing, token
normalization, maturity checks, and status precedence live here. The module has
no TOML, JSON, Markdown, project discovery, or filesystem imports.

### Render stage

`render.py` converts `StoryAudit` into the existing JSON payload and Markdown
text. It performs no validation, matching, or filesystem writes. This makes
serialization compatibility independently testable with fixed timestamps.

### Workspace stage

`workspace.py` keeps the two public workflows. Creation validates names/ids,
writes starter TOML, and returns `StoryWorkspaceResult`. Audit discovers the
project, parses the story, collects sources, evaluates steps, renders outputs,
writes both files, and returns the legacy-shaped `StoryAuditResult`.

No output file is written until parsing, source-kind validation, and audit
construction succeed. The existing behavior for missing sources still writes
blocked audit outputs.

## Dependency direction

```text
schema  -> models
sources -> models
audit   -> models
render  -> models
workspace -> schema + sources + audit + render + models
package facade -> workspace + models
```

`schema`, `sources`, `audit`, and `render` do not import `workspace`. Cycles are
forbidden. Project discovery and filesystem mutation remain in the application
layer rather than moving into `core/`.

## Testing strategy

Existing application and CLI tests remain unchanged as end-to-end compatibility
tests. New focused tests cover:

- raw TOML to `StorySpec` validation and exact existing diagnostics;
- artifact mapping normalization, including absent optional fields and tags;
- selector matching and all step/overall status combinations without I/O;
- exact JSON payload and Markdown rendering from a fixed typed audit;
- the package facade exporting the original five public symbols;
- no remaining `dict[str, Any]` or `Any` annotations in `models.py`, `audit.py`,
  or `render.py`.

The refactor is performed in dependency order with characterization tests before
each move. Each stage must pass its focused tests before the old helper is
removed from `story.py`.

## Coverage policy migration

The Wave 1 exact-file floor for
`src/runops/application/analysis/story.py = 80` is replaced when the module is
removed. The typed decision boundary receives stricter floors and I/O-heavy
modules retain the previous minimum:

| Module | Floor |
|---|---:|
| `story/models.py` | 95% |
| `story/schema.py` | 90% |
| `story/audit.py` | 95% |
| `story/sources.py` | 80% |
| `story/render.py` | 90% |
| `story/workspace.py` | 80% |

The policy remains exact-file based; no glob or aggregate coverage feature is
added. Floors must pass the real branch-coverage report before the refactor is
completed.

## Error handling and migration

Parsing and external artifact normalization translate malformed inputs to
`SimctlError` at the same boundary as today. Internal typed functions do not
catch programmer errors or silently coerce invalid domain records.

There is no user migration. `story.toml`, `audit.json`, `audit.md`, CLI command
names, and public result shapes do not change. Private underscore helpers from
the former module are not compatibility APIs and may move without re-export.

## Deferred decisions

- adding new Story schema fields or schema version 2;
- moving pure story models or decisions into `core/`;
- changing public result containers from dictionaries/lists to typed tuples;
- generating ActionSpec or MCP tools for story audit commands;
- aggregate directory or changed-line coverage policies.
