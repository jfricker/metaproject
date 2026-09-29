# The document set

`metaproject` scaffolds a fixed set of documents into every project. They are not
decoration — they are the working memory that lets an agent (or a person returning after
a month) pick the work up without re-deriving context. This is what each one is for and
when to touch it.

## The 7-stage cycle

Every cycle of work moves through seven stages, each owned by a project skill (copied
into `.agents/skills/` by `new`/`backfill`, invoked by bare name) and ticked off in
`docs/STATE.md`'s Process list. Every cycle document lives in `docs/`:

```
write-intent → generate-spec → generate-design → generate-plan →
implement-plan → execute-tests → wrapup
```

```
INTENT.md   SPEC.md    TECH-DESIGN.md  PLAN.md   code + tests    STATE.md      archive + reset
   why         what      how (tech)   how (steps)    verified       tracked        long-lived docs
```

- **write-intent** produces `docs/INTENT.md`: the problem, proposed outcome, affected users
  and systems, in the user's terms, not the implementation's.
- **generate-spec** turns an approved `docs/INTENT.md` into `docs/SPEC.md`: requirements and
  acceptance criteria.
- **generate-design** turns an approved `docs/SPEC.md` into `docs/TECH-DESIGN.md`: affected components,
  data flow, interfaces, trade-offs.
- **generate-plan** turns approved `docs/SPEC.md` + `docs/TECH-DESIGN.md` into `docs/PLAN.md`: files touched,
  sequencing, risks.
- **implement-plan** writes code and tests against the approved `docs/PLAN.md`, ticking off
  `docs/STATE.md`'s Implementation phases as steps land.
- **execute-tests** runs the quality gate and records verified facts / design invariants
  in `docs/STATE.md`.
- **wrapup** archives `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md` and (if
  present) `docs/HANDOFF.md` into `docs/archive/`, appends `docs/STATE.md`'s invariants and facts
  into `docs/DESIGN-INVARIANTS.md` and `docs/VERIFIED-FACTS.md`, updates
  `docs/ARCHITECTURE.md`'s cycle index, and resets the cycle documents to blank for the next
  one.

## Deliverable classes

- **governance** — `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`. Rendered and
  diffed in full, body-for-body; offered for both Update and Deploy.
- **working** — `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`,
  `docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`. Checked for
  heading structure only: a template heading with no matching heading in the project
  file is drift, body text is never diffed, and these are never offered for Update — you
  fill their content freely and `review` never second-guesses it.
- **on-demand** — `docs/HANDOFF.md`. Never scaffolded by `new`, never reported missing by
  `review`. Create it with `metaproject backfill docs/HANDOFF.md` only when work stops
  mid-stream.
- **directory** — `docs/`, `docs/archive/`. Presence checks, nothing more.

## `.metaproject.json`

`new` writes this at the project root — `title`, `description`, `author`, `created`,
`metaproject_version` — and it is tracked in git as part of the initial commit. Every
other command that needs variables (`review`, `learn`, `backfill`, `universe`) reads it
first; without it, title/description fall back to `README.md`, then
`pyproject.toml`, then `package.json`, then the directory name. `metaproject_version`
records which version of `metaproject` last brought the project's documents up to date;
`new` writes it, and `doctor` when it backfills a missing anchor. It is not itself a
reviewable deliverable — never diffed, never `DRIFTED` — and its absence is an
informational note from `review`, not `! INCOMPLETE`.

## The blank rule

A cycle document (`docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`) is **blank** iff its
first `# ` heading still contains the literal `<Title>`. This is the single rule every
skill and tool uses — `write-intent`'s precondition that there's no unfinished cycle,
`generate-spec`'s check that a stale spec hasn't been left behind, `wrapup`'s reset back
to blank. `docs/ARCHITECTURE.md` and the two long-lived `docs/` files use a
`{ProjectTitle}`-style header instead of the cycle header and are never blank.

## Status vocabulary

Cycle documents share one header:

```markdown
# <Title>[ — Spec|Design|Implementation Plan]

**Author**: ...
**Derived from**: ... (except INTENT.md)
**Last updated**: ...
**Status**: Draft.
**Approved by**: —
```

`Status` takes one of: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
`Superseded`. `Approved by` stays `—` until the operator signs off, then names them and
the date — that is the gate `implement-plan` checks before it starts writing code.

## `docs/INTENT.md`

The problem, the proposed outcome, affected users and systems. Written *before* spec or
design, in the user's terms. Starts `Draft`; becomes `Approved` before `generate-spec`
runs.

## `docs/SPEC.md`

What the system must do, derived from `docs/INTENT.md`: requirements (`R-…`) and acceptance
criteria (`AC-…`). The contract `docs/TECH-DESIGN.md` and `docs/PLAN.md` cite by requirement ID.

## `docs/TECH-DESIGN.md`

How `docs/SPEC.md`'s requirements get built: affected components, data flow, interfaces,
trade-offs, alternatives considered. `generate-plan` reads this alongside `docs/SPEC.md`.

## `docs/PLAN.md`

Sequenced implementation steps, files touched, risks and rollback. `implement-plan`
follows it strictly; deviations get recorded, not silently taken.

## `docs/STATE.md`

The live record of where the work actually is. The scaffolded skeleton:

```markdown
# {ProjectTitle} — State

## Process

<!-- each stage ticks its own item here as it completes -->
- [ ] 1. write-intent: INTENT.md approved
- [ ] 2. generate-spec: SPEC.md approved
- [ ] 3. generate-design: TECH-DESIGN.md approved
- [ ] 4. generate-plan: PLAN.md approved
- [ ] 5. implement-plan: code and tests written
- [ ] 6. execute-tests: tests passing
- [ ] 7. wrapup: cycle archived

## Implementation phases

<!-- written by implement-plan as steps land -->

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to docs/DESIGN-INVARIANTS.md by wrapup -->

## Open items carried into PLAN.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to docs/VERIFIED-FACTS.md by wrapup -->
```

Two sections earn their keep and are the ones most often neglected:

- **Design invariants (regression guards)** — properties that must keep holding. When a
  bug is fixed by establishing a rule ("rollback never deletes a pre-existing file"),
  record the rule here, not just the fix. It is what stops the same class of bug
  returning under a different name.
- **Verified facts (do not re-investigate)** — things established at cost that would
  otherwise be re-litigated every session ("the TUI degrades correctly under `TERM=dumb`;
  confirmed 2026-09-05"). Include the date; a verified fact has a shelf life.

Update `docs/STATE.md` as phases land, not in a single sweep at the end. A `docs/STATE.md` that is
only accurate at release time is a changelog, and there are better changelogs.

## `docs/HANDOFF.md`

On-demand — not scaffolded, never reported missing. Create it (`metaproject backfill
docs/HANDOFF.md`) when work is **interrupted before completion**, not routinely. It answers
one question: what does the next session need in order to continue — current state,
SDLC stage, branch/worktree, last commit, command(s) to re-run, next steps, blockers.

The failure mode is writing it as a summary of what was done. Bias it toward what is
*unfinished*.

## `docs/ARCHITECTURE.md`

Long-lived, never reset. `wrapup` appends each cycle's summary to its cycle index; it is
the sum of every cycle's decisions, not a from-scratch description rewritten each time.

## `docs/DESIGN-INVARIANTS.md`

Long-lived, append-only. `wrapup` moves `docs/STATE.md`'s "Design invariants" section here,
dated and linked to the cycle's archive, before resetting `docs/STATE.md`. Read it before
`generate-spec`/`generate-design`/`generate-plan` so an invariant from one cycle isn't
accidentally violated in the next.

## `docs/VERIFIED-FACTS.md`

Long-lived, append-only. `wrapup` moves `docs/STATE.md`'s "Verified facts" section here the
same way. Read it before re-deriving something a prior cycle already confirmed.

## `docs/`, `docs/archive/`

Directory deliverables — presence checks only. `docs/archive/<date>-<slug>/` is where
`wrapup` moves a completed cycle's `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`,
`docs/STATE.md` and `docs/HANDOFF.md` (if present).

## `AGENTS.md`

How to work in this repository: dev environment, build commands, testing instructions,
the quality gate to run before committing, release process, architecture, key files.

This is the file an agent reads first, so precision pays. `make format && make lint &&
make test` as a stated gate is worth more than a paragraph about caring for quality.

## `CLAUDE.md`

Project-specific instructions for Claude. Short by design, and it points at `AGENTS.md`
rather than duplicating it — two files drifting apart on the same subject is worse than
one.

## `README.md`

For humans arriving at the project: what it is, how to start, where the docs are.

---

## Working in a metaproject-managed repo

When you are making changes in a project that has these files:

1. Read `AGENTS.md` first — it tells you the build and test commands, and the gate to run
   before committing. Following it beats inferring conventions from the code.
2. Check `docs/STATE.md` for design invariants and verified facts before investigating
   something that looks unresolved. It may already be settled — and so might
   `docs/DESIGN-INVARIANTS.md` / `docs/VERIFIED-FACTS.md` from a prior cycle.
3. Update `docs/STATE.md` when a phase lands. Part of finishing the work, not a follow-up.
4. Write `docs/HANDOFF.md` (via `metaproject backfill docs/HANDOFF.md`) if you stop mid-stream.
5. If a document `review` reports missing, use `metaproject backfill docs/<FILE>.md` rather than
   hand-writing it — it renders from the same template the rest of the fleet uses.
6. If a convention you followed here would serve every project, that is exactly what
   `metaproject learn` harvests — mention it rather than editing the template store
   directly.
