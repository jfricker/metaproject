# The document set

`metaproject` scaffolds a fixed set of documents into every project. They are not
decoration — they are the working memory that lets an agent (or a person returning after
a month) pick the work up without re-deriving context. This is what each one is for and
when to touch it.

## The SDLC flow

The documents are sequenced, and `STATE.md` opens by naming the sequence:

```
intent.md  →  spec.md  →  plan.md  →  implementation
   why           what        how          verified work
```

- **`intent.md`** — the problem, the proposed outcome, affected users and systems. Written
  *before* design, in the user's terms, not the implementation's. It carries a status
  (Draft / Designed / Superseded); when a design supersedes an earlier section, say so in
  place rather than deleting the history — the reasoning is the value.
- **`spec.md`** — what the system must do, derived from intent. The contract.
- **`plan.md`** — how it will be built, in phases that can be verified independently.
- **`STATE.md`** — the live record of where the work actually is.

`spec.md` and `plan.md` are not scaffolded by the templates; they are created from
`intent.md` as the work moves through the first two checklist items in `STATE.md`.

## STATE.md

The scaffolded skeleton:

```markdown
## Process
- [ ] 1. Review intent.md and create spec.md
- [ ] 2. Create plan.md from spec.md
- [ ] 3. Implementation and verification

## Implementation phases
## Design invariants (regression guards)
## Open items carried into plan.md
## Verified facts (do not re-investigate)
```

Two sections earn their keep and are the ones most often neglected:

- **Design invariants (regression guards)** — properties that must keep holding. When a
  bug is fixed by establishing a rule ("rollback never deletes a pre-existing file"),
  record the rule here, not just the fix. It is what stops the same class of bug
  returning under a different name.
- **Verified facts (do not re-investigate)** — things established at cost that would
  otherwise be re-litigated every session ("the TUI degrades correctly under `TERM=dumb`;
  confirmed 2026-09-05"). Include the date; a verified fact has a shelf life.

Update `STATE.md` as phases land, not in a single sweep at the end. A `STATE.md` that is
only accurate at release time is a changelog, and there are better changelogs.

## HANDOFF.md

Written when work is **interrupted before completion** — not routinely. It answers one
question: what does the next session need in order to continue?

```markdown
## Current State        — what was in progress at the moment of interruption
## Immediate Next Steps — ordered, concrete, resumable without archaeology
## Open Issues or Blockers
```

The failure mode is writing it as a summary of what was done. Bias it toward what is
*unfinished*: the half-applied migration, the test that fails for a reason not yet
understood, the decision that was still open.

## AGENTS.md

How to work in this repository: dev environment, build commands, testing instructions,
the quality gate to run before committing, release process, architecture, key files.

This is the file an agent reads first, so precision pays. `make format && make lint &&
make test` as a stated gate is worth more than a paragraph about caring for quality.

## CLAUDE.md

Project-specific instructions for Claude. Short by design, and it points at `AGENTS.md`
rather than duplicating it — two files drifting apart on the same subject is worse than
one.

## README.md

For humans arriving at the project: what it is, how to start, where the docs are.

## docs/

Longer-form documentation and specifications. Scaffolded with a `.gitkeep` so the
directory survives an empty commit.

---

## Working in a metaproject-managed repo

When you are making changes in a project that has these files:

1. Read `AGENTS.md` first — it tells you the build and test commands, and the gate to run
   before committing. Following it beats inferring conventions from the code.
2. Check `STATE.md` for design invariants and verified facts before investigating
   something that looks unresolved. It may already be settled.
3. Update `STATE.md` when a phase lands. Part of finishing the work, not a follow-up.
4. Write `HANDOFF.md` if you stop mid-stream.
5. If a convention you followed here would serve every project, that is exactly what
   `metaproject learn` harvests — mention it rather than editing the template store
   directly.
