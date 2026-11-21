# MetaProject Learn — Implementation Plan

**Reference**: [spec.md](file:///Users/johnfricker/Projects/MetaProject/spec.md) | [intent.md](file:///Users/johnfricker/Projects/MetaProject/intent.md) | [STATE.md](file:///Users/johnfricker/Projects/MetaProject/STATE.md)
**Status**: draft
**Runtime**: Python 3.11+ via `uv`

---

## 1. Overview & Architecture Strategy

### 1.1 What changes

`src/metaproject/learn.py` is replaced by a `src/metaproject/learn/` package. The current
module's three public functions (`extract_file_additions`, `learn_from_project`,
`apply_learned_enhancement`) are deleted rather than adapted — the line-diff model they
implement is the thing being removed, not a foundation to build on.

### 1.2 Module boundaries

Each module owns one stage and is testable without the others. Only `store.py` touches
SQLite; only `synth.py` touches the model; only `apply.py` writes to the template store.

| Module | Responsibility | Depends on |
|---|---|---|
| `collect.py` | Render each template with a project's variables, diff against the project's file, emit evidence records. | `templates`, `variables`, `universe` |
| `guard.py` | Filter `.gitignore` and denylist; redact secrets; build the confirmation manifest. | stdlib only |
| `synth.py` | Assemble per-target-file bundles, chunk when over budget, invoke `claude -p`, parse structured output. | `guard` output only |
| `score.py` | Frequency + recency + activity weighting; queue ordering. | `universe` classifications |
| `store.py` | `learn_proposals` / `learn_evidence` / `learn_runs` CRUD, content hashing, suppression and resurfacing. | `db` |
| `apply.py` | Patch a template at its target section; commit to the template repository. | `git`, `store` |
| `tui.py` | `rich` review loop; each keystroke delegates to the same functions the subcommands call. | `store`, `apply` |
| `__init__.py` | Public API — `scan()`, `review()`, `apply_proposal()`, `reject_proposal()` — consumed by `cli.py`. | all of the above |

### 1.3 Governing principles

1. **The model judges; code does everything else.** Evidence gathering, redaction,
   scoring, persistence, and writing are deterministic and independently testable. Model
   output is data — parsed, validated, stored, and inserted as template text. It is never
   executed and never treated as an instruction to the tool.
2. **One queue, two interfaces.** The TUI calls the same functions as the subcommands.
   There is no TUI-only code path that can diverge in behavior.
3. **Scan never writes.** The separation between scan and apply is the primary safety
   property, and is asserted directly by a test.
4. **No new dependency.** `rich` is already approved and carries the TUI.

### 1.4 Sequencing rationale

Phases are ordered so that the deterministic core is complete and tested before the model
enters the picture, and the model path is complete before the interactive layer sits on
top of it. Phases 1–2 are verifiable with no `claude` binary present at all.

---

## 2. Implementation Phases & Gate Criteria

### Phase 0 — Schema & configuration

Add `learn_proposals`, `learn_evidence`, and `learn_runs` to `db.init_schema`, with the
indexes named in spec §5.4.8. Add the `learn` block to the `Config` dataclass with the
defaults in spec §4.2. Extend `metaproject init` to `git init` the templates directory
(default branch `main`, initial commit `chore: initial template store`), idempotently for
an existing store.

**Gate**: schema creates cleanly on a fresh and on an existing `universe.db`; config
round-trips with and without the `learn` key present (forward compatibility); `init` is
idempotent against an already-git-backed template directory.

### Phase 1 — Collect & guard

Implement `collect.py` and `guard.py`. Delete the legacy `learn.py`.

**Gate**: a project whose file matches its rendered template produces zero evidence — the
placeholder false-positive class is gone; `.gitignore`d and denylisted paths never appear
in output; high-entropy strings are redacted; the manifest lists exactly what would be
sent. No model involved.

### Phase 2 — Score & store

Implement `score.py` and `store.py`.

**Gate**: frequency, recency, and activity weights combine into a stable ordering; a
single-project candidate surfaces and ranks below a corroborated one; proposals upsert by
`content_hash`; a rejected hash stays suppressed across scans and resurfaces exactly when
`evidence_score > rejected_score * resurface_factor`; `--forget` clears it.

### Phase 3 — Synthesize

Implement `synth.py`: prompt construction, per-target-file bundling, chunk-and-reduce,
subprocess invocation, structured output parsing and validation.

**Gate**: exactly one call per target file for an in-budget bundle; an over-budget bundle
chunks and reduces; malformed output retries once then marks the run `partial` and skips
that file; a missing `claude` binary exits non-zero having written nothing. The `claude`
subprocess is mocked in every test — no test invokes a model.

### Phase 4 — Apply

Implement `apply.py` and wire `learn scan`, `list`, `show`, `apply`, `edit`, `reject` into
`cli.py`.

**Gate**: the proposal lands under its `target_section` rather than appended at EOF;
`edited_body` takes precedence over `proposed_body`; each accept is one commit carrying
proposal id and contributing project names; `apply` refuses on a dirty template
repository; **a full `learn scan` leaves the template store byte-identical and its git
worktree clean.**

### Phase 5 — Acceptance TUI

Implement `tui.py` and make bare `metaproject learn` the scan-then-review default. Add
`learn review`.

**Gate**: every keybinding produces the same state transition as its equivalent
subcommand, asserted directly; Skip leaves `pending`, Discard marks `rejected`; quitting
mid-session persists everything already actioned and loses nothing; non-TTY, `--no-tui`,
and `TERM=dumb` fall back to the `list` table and exit zero; a narrow terminal falls back
to the unified view; an empty queue does not open the TUI.

### Phase 6 — `new_template` proposals & `review` integration

Emit `kind: "new_template"` for recurring untemplated files. Feed `review` drift findings
into `evidence_score`.

**Gate**: a file recurring across projects with no template produces a `new_template`
proposal that applies as a new file in the template store; drift that `review` already
reports raises the corresponding pattern's score rather than creating a parallel finding.

### Phase 7 — Documentation & release

Update `README.md`, `AGENTS.md`, and `STATE.md`. Run `make lint`, `make test`,
`make build`, then `make bump-version`.

**Gate**: `make lint` and `make test` clean; `--help` output for every `learn` subcommand
matches spec §5.4.4.

---

## 3. Risk Analysis & Mitigation Matrix

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | **Secret leakage via model egress.** A project file carries a credential that reaches `claude`. | High | Diffs only, never whole files. `.gitignore` plus a hard denylist plus entropy redaction, layered. Send manifest confirmed once per session. Tested in Phase 1 against planted secrets before any model code exists (Phase 3). |
| R2 | **Prompt injection from project content.** A scanned `AGENTS.md` contains text addressed to the model or to the tool. | High | Model output is parsed as structured data and validated against a schema; unparseable output is discarded, not interpreted. A proposal body becomes template text only, is never executed, and never alters tool behavior. Every write still passes a human diff review. |
| R3 | **Non-deterministic output destabilizes the queue.** Re-scanning yields differently-worded proposals for the same underlying pattern, so `content_hash` misses and suppressed candidates resurface as "new". | High | Hash normalized content, not raw model prose. Track this explicitly during Phase 3 — if hashing proves unstable in practice, the fallback is hashing the deterministic evidence set rather than the generated body. |
| R4 | **Context budget overrun** on a large workspace bundling many projects into one call. | Medium | Chunk-and-reduce specified and gated in Phase 3. Budget is measured, not assumed. |
| R5 | **Cost and latency** scale with target files × workspace size. | Medium | One call per target file, not per project × file. `--target` narrows a run; `--since` limits to recently-changed projects. |
| R6 | **Bad accept corrupts a template**, silently degrading every subsequently scaffolded project. | Medium | Git-backed template store; one commit per accept, so a single revert undoes exactly one decision. `apply` refuses on a dirty worktree. |
| R7 | **Structural insertion is wrong** — the model names a `target_section` that does not exist, or the splice mangles the document. | Medium | Validate `target_section` resolves before writing; fall back to a reviewed append rather than a silent misplacement. The operator sees the rendered diff before any write. |
| R8 | **`claude` CLI interface drift** — flags or output format change under us. | Medium | Invocation confined to `synth.py`. Hard failure with a clear message on a missing binary or unparseable output; never a silent fallback to the old heuristic. |
| R9 | **Scope creep in the TUI** toward a full widget framework, pulling in `textual`. | Low | `rich` is the decision. Side-by-side and unified diffs are `rich` tables; the loop reads keystrokes and repaints. Revisit only if a gate cannot be met. |
| R10 | **Regression in `new`/`review`** from the shared `db` and `config` changes. | Low | Additive schema and config changes only; existing tests must stay green at every phase gate. |
