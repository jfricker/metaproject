# Make metaproject the source of truth for SDLC document templates — Design

**Author**: Claude.
**Derived from**: spec.md (2026-09-14).
**Last updated**: 2026-09-14.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-14).

Requirement IDs refer to spec.md. Module paths are under `src/metaproject/` unless noted.

## Affected components

### New modules

- **`deliverables.py`** — the single declaration of deliverable classes (R-CLS-1).
  ```python
  class DeliverableClass(Enum): GOVERNANCE, WORKING, ON_DEMAND, DIRECTORY
  @dataclass(frozen=True)
  class Deliverable: path: str; cls: DeliverableClass
  DELIVERABLES: tuple[Deliverable, ...]          # ordered: board order
  def classify(path) -> DeliverableClass | None
  def scaffolded() -> tuple[str, ...]            # everything except ON_DEMAND
  def learn_targets() -> tuple[str, ...]         # GOVERNANCE + WORKING
  ```
  Replaces `review.STANDARD_DELIVERABLES` and becomes the source of
  `config.DEFAULT_LEARN_TARGETS` (R-LRN-3). `docs/archive` is a DIRECTORY entry.
- **`markdown.py`** — heading parsing shared by `review`, `learn.collect` and
  `learn.apply`. `Section`, `iter_sections`, `normalize_heading` move here unchanged from
  `learn/apply.py` (which re-imports them). Adds:
  ```python
  def headings(text) -> list[Heading]            # (level, title), fence-aware
  def heading_matches(template: Heading, project: Heading) -> bool
  def missing_headings(template_text, project_text) -> list[Heading]   # R-CLS-3
  ```
  `heading_matches`: same level, and `normalize_heading(project)` starts with
  `normalize_heading(template)`; a template title containing `<…>` matches any title at
  that level. Matching is order-insensitive and one-to-one (each project heading
  satisfies at most one template heading).
- **`identity.py`** — `.metaproject.json` (R-ID-1…4).
  ```python
  IDENTITY_FILE = ".metaproject.json"
  @dataclass(frozen=True)
  class Identity: title; description; author; created: date; metaproject_version
  def read_identity(project_dir) -> Identity | None      # tolerant: bad JSON -> None + warning
  def write_identity(project_dir, identity) -> Path      # pretty JSON, sorted keys, trailing \n
  def fallback_identity(project_dir) -> tuple[title, description]   # README -> pyproject -> package.json -> dir
  ```

### Changed modules

- **`variables.py`** — `collect_variables(..., created: date | None = None)`: `Date`/`Year`
  render from `created` when given, else today (only `new` uses today). New
  `project_variables(project_dir, config)` moves here from `learn/collect.py`: identity
  file first, else `fallback_identity`, `created=identity.created` when present
  (R-ID-2). `learn.collect.project_variables` and `review.resolve_variables` delegate to
  it; `_drop_unfilled_placeholder` is kept for README fallbacks.
- **`universe.py`** — `extract_title`/`extract_description` delegate to
  `identity.read_identity` then `fallback_identity`; the `intent.md` branches and the
  `split("-")[0]` are deleted (R-ID-3).
- **`templates.py`** — `find_unknown_placeholders(text) -> list[str]` using the same regex
  as `preprocess_template_string`, minus `WHITELISTED_VARS` (R-TPL-3).
  `render_template_tree(..., exclude: Collection[str] = ())` skips transformed relative
  paths in `exclude`, and returns warnings via a new `RenderReport(paths, warnings)`
  (existing callers updated; `seed_templates` unchanged).
- **`scaffold.py`** — `scaffold_project` passes `exclude=ON_DEMAND paths`; after rendering,
  writes `.metaproject.json` unless it exists (tracked for rollback, listed in dry-run,
  written before `init_repository` so the initial commit includes it) (R-ID-1, R-CLS-5).
  Returns `warnings`.
- **`review.py`**
  - `ReviewResult` gains `structure: Dict[str, List[str]]` (working deliverable → missing
    heading lines), `notes: List[str]` (e.g. "no .metaproject.json") and
    `warnings: List[str]`. `diffs` stays governance-only, so `updatable` (=
    `sorted(diffs)`) can never contain a working deliverable (R-CLS-4). `is_clean`
    becomes `not missing_files and not diffs and not structure`.
  - `review_project` iterates `DELIVERABLES`: skip ON_DEMAND; DIRECTORY → presence;
    GOVERNANCE → existing render-and-diff; WORKING → `markdown.missing_headings` against
    the rendered template. Absent identity → `notes` (R-ID-4).
  - `update_entry` raises `MetaProjectError` for a non-governance deliverable.
  - New `backfill_missing(project_dir, files=None, templates_dir=None, dry_run=False)
    -> BackfillResult(created, skipped, refused)` built on `deploy_entry` with one
    `resolve_variables` per call. No files → every missing `scaffolded()` deliverable,
    DIRECTORY entries first, re-checking existence after each (a rendered `docs/` tree
    may create later entries). Files named → all must be absent or nothing is written.
- **`review_tui.py`** — drifted column counts `diffs` + `structure`; a working
  deliverable's detail shows "missing headings: …" instead of a diff and has no `u`
  action; `u all` pool stays `updatable`.
- **`cli.py`**
  - New `backfill` command (R-TPL-8): `files: List[str] = Argument(None)`,
    `--dir/-d`, `--templates`, `--dry-run`. No agent guard. Prints created / skipped
    (exists) / refused; exit 1 on refusal or missing template.
  - `new`: prints template warnings and "wrote .metaproject.json".
  - `review`: board shows `structure` drift and `notes`; prints warnings.
  - User-facing text for `new .` stops saying "backfill" (becomes "scaffold into an
    existing directory") so the word names one command; function names
    (`confirm_backfill`, `backfill=` parameter) are internal and unchanged.
- **`config.py`** — `DEFAULT_LEARN_TARGETS = deliverables.learn_targets()`; existing
  pinned `learn.targets` untouched (doctor, FC-3).
- **`learn/collect.py`** — `EvidenceRecord` gains `removed_lines: Tuple[str, ...] = ()`.
  For a WORKING target, `collect_project` builds a *structural* record: `kind="structure"`,
  `added_lines` = project headings with no template match (as `"## Title"` lines),
  `removed_lines` = template headings with no project match, only when the project file
  is non-empty (R-LRN-1b), `diff` = unified diff of the two heading lists. ON_DEMAND
  targets are never collected.
- **`learn/structure.py`** (new, deterministic) — turns structural records into proposals
  without a model (see Data flow). Kinds `add_heading` / `remove_heading`.
- **`learn/api.py`** — `scan` partitions records: structural → `structure.propose`;
  everything else → `guard_evidence` → `synthesize` as today. Structural records never
  enter the guard manifest, the egress confirmation, or any prompt (R-LRN-1).
- **`learn/apply.py`** — `plan_apply` handles `add_heading` via existing `splice`
  (`target_section` = anchor heading; body = heading line) and `remove_heading` via new
  `excise(text, section)` removing `lines[section.heading:section.end]`.
- **`learn/drift.py`** — `collect_drift` reads `result.structure` for working
  deliverables: a missing heading reported by review corroborates a `remove_heading`
  key; an extra heading is not reported by review, so additions get no drift boost
  (R-LRN-4).
- **`learn/synth.py`** — `bundle_evidence` ignores `kind="structure"` records
  (defensive; api already filters).

### Templates (`src/metaproject/templates/`)

Repo-root `templates/` deleted (R-TPL-1). Added/changed files:

```
AGENTS.template.md          rewritten (R-TPL-7)
CLAUDE.template.md          "@AGENTS.md" + Claude notes
README.template.md          docs pointer fixed
STATE.template.md           7-item Process + per-section stage comments
HANDOFF.template.md         on-demand; new sections
intent.template.md          shared cycle header, <…> placeholders
spec.template.md            new
design.template.md          new
plan.template.md            new
ARCHITECTURE.template.md    new ({ProjectTitle} header, cycle index table)
.gitignore.template         + .claude/worktrees/
docs.template/.gitkeep
docs.template/DESIGN-INVARIANTS.template.md   new
docs.template/VERIFIED-FACTS.template.md      new
docs.template/archive.template/.gitkeep       new (-> docs/archive/.gitkeep)
```

Cycle-doc header (intent omits `Derived from`):

```markdown
# <Title> — Spec

**Author**: {Author}.
**Derived from**: intent.md (<date>).
**Last updated**: {Date}.
**Status**: Draft.
**Approved by**: —
```

`{Date}` in a working doc is harmless: working docs are structure-checked, not diffed.

### metaproject docs

`skill/SKILL.md`, `skill/references/documents.md`, `skill/references/commands.md`
(R-DOC-1); `README.md` command table; `AGENTS.md` (this repo) mentions `backfill`.
`docs/discovery/2026-09-04-learn-cycle-open-observations.md` and
`docs/archive/2026-09-04-improve-learn-command/README.md` (R-DOC-2).

### sdlc-skills (`~/Projects/SDLC-skills`)

- **`hooks/hooks.json`** + **`hooks/check-metaproject.sh`** (R-SK-2):
  ```json
  {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
    "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-metaproject.sh"}]}]}}
  ```
  Script (POSIX sh, read-only): `root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)`;
  `command -v metaproject` else install notice; version = first `X.Y.Z` on the line of
  `metaproject --version` output containing "Version", compared with `sort -V` against
  `0.7.0`; `[ -f "$root/.metaproject.json" ]` else scaffold notice. Silent on success;
  always exit 0; stdout becomes session context.
- **`Makefile`** (R-NF-7): `help`, `test` → `sh tests/test_check_metaproject.sh`, which
  runs the hook against temp dirs with a stub `metaproject` on `PATH` (AC-14a cases).
- **`skills/*/SKILL.md`** (R-SK-1…7): remove "Blank template" blocks; add a shared
  preamble paragraph (same wording in each): *Session assumption* (R-SK-2a),
  *Documents come from metaproject* (`metaproject backfill <file>` when missing),
  *Blank rule*, *Status vocabulary / Approved by*, *Tick your STATE.md Process item*.
  wrapup's process rewritten per R-SK-7; its inline ARCHITECTURE/long-lived templates
  removed.
- **`README.md`, `AGENTS.md`** — metaproject ≥ 0.7.0 required; templates owned by
  metaproject; merge order note. Root docs (intent/spec/design/plan/STATE) re-headed to
  the new templates; `.metaproject.json` via operator `metaproject new .` (R-SK-8).
- **`.claude-plugin/plugin.json`** version `0.0.2` (R-REL-2).

## Data flow / interfaces

### `metaproject new`
```
collect_variables(today) ─▶ render_template_tree(store, exclude=ON_DEMAND) ─▶ RenderReport
                         └▶ write_identity(.metaproject.json, created=today, version)
                         └▶ link_agent_skills ─▶ init_repository (commits all, incl. identity)
warnings ─▶ console
```

### `metaproject review`
```
project_variables(project) ── identity? ─yes─▶ created/title/description from JSON
                                   └─no──▶ README/pyproject/package.json; note "no identity"
for d in DELIVERABLES:
  ON_DEMAND  → skip
  DIRECTORY  → exists? else missing
  GOVERNANCE → render → unified diff → diffs[d]        (Update/Deploy)
  WORKING    → render → missing_headings → structure[d] (Deploy only)
```

### `metaproject backfill [FILE...]`
```
resolve_variables(project) once
targets = FILE... or [d for d in scaffolded() if missing]   (directories first)
named & any exists → refuse all, exit 1
each target: deploy_entry(...)   # existing create-only writer; never git
```

### `learn scan`
```
collect_project ─┬─ GOVERNANCE record (edit/new_template) ─▶ guard ─▶ confirm egress ─▶ synthesize (model)
                 └─ WORKING  record (structure)            ─▶ structure.propose (local, no model)
both ─▶ score weights × drift ─▶ upsert_proposal ─▶ learn list/show/apply
```

`structure.propose(records, weights, drift)`:
- Key: `(target_file, op, level, normalize_heading(title))`, op ∈ {add, remove}; a level
  change is naturally one remove + one add.
- Contributors: distinct projects; score = sum of weights (same `score.weigh_project`).
- Emit a proposal only when distinct contributors ≥ `learn.min_structure_evidence`
  (default 2) — see Trade-offs.
- `add_heading`: `target_section` = the anchor most contributors place it after (nearest
  preceding heading in the project file that matches a template heading); body =
  `"#"*level + " " + title`; title/rationale generated from counts.
- `remove_heading`: `target_section` = the template heading; refused (not emitted) if the
  template section contains child headings that any contributor still has.
- `content_hash(target_file, body, kind)` as today, so reject/resurface semantics carry
  over unchanged.

### sdlc-skills session
```
SessionStart hook ─▶ (silent) | notice in context
skill ─▶ trusts assumption ─▶ reads/edits working doc
       └▶ doc missing ─▶ metaproject backfill <file>
wrapup ─▶ Status: Complete ─▶ append invariants/facts ─▶ git mv 5–6 docs to archive
       ─▶ metaproject backfill (all missing) ─▶ seed intent Open questions ─▶ commit
```

## Alternatives considered

- **Classification as a flag on `STANDARD_DELIVERABLES` entries vs. a `deliverables.py`
  module.** A module wins: `review`, `scaffold`, `config` and `learn` all need it, and
  `learn` must not import `review` for a constant.
- **Structural drift in `diffs` with a marker vs. a separate `structure` field.** A
  separate field makes "working docs are never updatable" a property of the type
  (`updatable` reads `diffs` only) rather than a filter someone can forget.
- **Heading proposals via the model vs. deterministic.** Deterministic: heading add/remove
  needs no judgment, needs no egress confirmation, and is fully testable without mocks.
  The optional one-line section comment (R-LRN-1a) is therefore not generated in v1;
  an operator can add it with `learn edit`.
- **`backfill` as a `review --deploy` flag vs. a top-level command.** Top-level: `review`
  is read-only for agents today; adding a write flag to it blurs that.
- **Falling back to bundled templates when the live store lacks a new file.** Rejected:
  it silently creates a second source of truth — the problem this cycle removes. A
  missing template is an error pointing at FC-3 (manual refresh / future doctor).
- **Adding `metaproject --version --short` for the hook.** Rejected for scope; the hook
  parses the existing output. Revisit if the output format changes.
- **Identity as a `pyproject.toml` table.** Rejected by operator: not language-neutral.

## Trade-offs and risks

- **Minimum structural evidence (2) changes "ranked, not gated"** from the archived learn
  spec, for heading proposals only (approved). Without it, every project-specific heading
  becomes a one-project proposal and floods the queue. Configurable.
- **Legacy projects (no `.metaproject.json`) still get `{Date}` drift** on governance
  files that use it; only `new .` fixes them. Bundled governance templates don't use
  `{Date}` except HANDOFF (on-demand), so practical impact is low.
- **Prefix matching** (`## Scope` satisfied by `## Scope creep`) can hide a genuinely
  removed heading. Accepted in spec review.
- **`remove_heading` excises a subtree.** Mitigated by refusing to emit when a child
  heading is still used, and `learn show` lists the excised lines.
- **Moving `project_variables`/heading helpers** touches import paths used by tests;
  re-exports kept in the old locations for one release to avoid churn.
- **Hook version parsing** depends on the rich table output of `--version`; AC-14a's stub
  pins the expected format, so a format change fails `make test` in sdlc-skills.
- **Plugin hook contract** (`${CLAUDE_PLUGIN_ROOT}`, SessionStart stdout as context) to be
  confirmed against current Claude Code docs during implementation.
- **Existing projects become INCOMPLETE** (FC-2, accepted); `review --all` output will be
  noisy until the operator backfills.
- **Live store** lacks new templates until refreshed by hand (FC-3); sdlc-skills'
  `backfill` calls fail with a clear error until then.

## Open questions

None open. Resolved by John Fricker, 2026-09-14:

1. `learn.min_structure_evidence` defaults to 2. This deliberately changes the archived
   learn spec's "ranked, not gated" rule for structural (heading) proposals only; model
   proposals for governance files remain ungated.
2. v1 heading proposals carry no generated section comment; the operator adds one with
   `learn edit`.
