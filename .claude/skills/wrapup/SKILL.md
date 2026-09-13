---
name: wrapup
description: End-of-cycle archive and reset. Archives intent.md, spec.md, design.md, plan.md, and HANDOFF.md into docs/archive/, appends STATE.md's Design invariants and Verified facts into the long-lived docs/DESIGN-INVARIANTS.md and docs/VERIFIED-FACTS.md, updates ARCHITECTURE.md's cycle index, removes worktrees created for the cycle, and resets those docs (plus STATE.md) back to blank templates so main is ready for the next write-intent cycle. Touches only SDLC documents, ARCHITECTURE.md, docs/DESIGN-INVARIANTS.md, docs/VERIFIED-FACTS.md, docs/archive/, and worktrees — never source code or tests. Final step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# wrapup

Closes the loop: once a cycle's work is done, archive everything it produced, preserve
what's worth keeping long-term, and reset the repo root to a blank slate for the next
`write-intent`.

**Scope discipline**: this skill only ever touches SDLC documents (`intent.md`,
`spec.md`, `design.md`, `plan.md`, `HANDOFF.md`, `STATE.md`), the long-lived docs
(`ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`), the
`docs/archive/` directory, and git worktree bookkeeping. It never edits source code,
tests, or opens a PR — if any of those are still outstanding, the cycle isn't done; send
the user back to `execute-tests`/`implement-plan` instead of running `wrapup`.

## When to use

- The user says the current cycle's work is finished and ready to close out.
- `intent.md` at the repo root shows `Status: Approved` and the work it describes is
  actually done — don't archive an in-flight or abandoned cycle without confirming with
  the user first.

## Inputs

- The current `intent.md`, `spec.md`, `design.md`, `plan.md`, `HANDOFF.md` (if present),
  and `STATE.md` at the repo root.
- `ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md` — create each
  from its blank template (below) if it doesn't exist yet; otherwise append/update.
- `git worktree list` for any worktrees created during this cycle.

## Process

1. Confirm with the user which cycle is being closed if it's at all ambiguous (more than
   one `intent.md`-shaped thing could be meant).
2. **PRs are optional in this workflow (per `AGENTS.md`) — don't assume either way.**
   Ask the operator whether this cycle went through a PR:
   - If yes, verify it's merged before continuing.
   - If no, get explicit confirmation from the operator that the cycle's work is
     finished and committed (to `main` or wherever they're closing it from).
   Do not archive/reset until this is confirmed one way or the other.
3. Derive an archive slug from `intent.md`'s title and today's date:
   `docs/archive/YYYY-MM-DD-<slugified-title>/`.
4. Confirm `docs/archive/` already exists and is tracked (`git ls-files docs/archive/`
   should list at least `docs/archive/.gitkeep`) — this is a precondition of the repo,
   not something this step creates. If it's missing, stop and tell the user rather than
   `mkdir -p`-ing it into existence; a missing archive root means the repo scaffold is
   broken and needs fixing outside `wrapup`'s scope. Once confirmed, `git mv` (or move +
   `git add`) each of `intent.md`, `spec.md`, `design.md`, `plan.md`, and `HANDOFF.md`
   (if present) into the derived archive directory, preserving history.
5. Remove worktrees created for this cycle: for each one listed by `git worktree list`
   under `.claude/worktrees/` that belongs to this cycle, run
   `git worktree remove <path>` (add `--force` only after confirming with the user
   there's nothing uncommitted worth keeping in it).
6. **Preserve long-lived knowledge before it's lost to the STATE.md reset:**
   - If STATE.md's **Design invariants (regression guards)** section has content,
     append it to `docs/DESIGN-INVARIANTS.md` under a new dated heading linking to this
     cycle's archive directory (see template below). Skip if the section is empty.
   - If STATE.md's **Verified facts (do not re-investigate)** section has content,
     append it to `docs/VERIFIED-FACTS.md` the same way. Skip if empty.
   - Add a row to `ARCHITECTURE.md`'s cycle index: date, slug, a one/two-line summary of
     what the cycle did, links to the archived `spec.md`/`design.md`. If `design.md`'s
     Affected components / Data flow sections describe a structural change, amend
     `ARCHITECTURE.md`'s existing mermaid diagram(s) to reflect it — update in place,
     don't regenerate from scratch each cycle.
7. Recreate blank templates at the repo root for `intent.md`, `spec.md`, `design.md`,
   `plan.md`, using the same blank shapes defined in `write-intent`, `generate-spec`,
   `generate-design`, and `generate-plan` respectively (don't invent a divergent shape
   here — reuse those).
8. Reset `STATE.md`'s checklist back to:
   ```markdown
   # <Project> — State

   ## Process
   - [ ] 1. Review intent.md and create spec.md
   - [ ] 2. Create plan.md from spec.md
   - [ ] 3. Implementation and verification

   ## Implementation phases

   ## Design invariants (regression guards)

   ## Open items carried into plan.md

   ## Verified facts (do not re-investigate)
   ```
   Keep the project title line as it already reads; don't rename the project. This is
   safe now because step 6 already preserved the invariants/facts elsewhere.
9. Commit the archive + long-lived doc updates + reset as one commit (e.g.
   `chore: archive <slug> cycle, reset SDLC docs`).

## Blank templates

`docs/DESIGN-INVARIANTS.md` / `docs/VERIFIED-FACTS.md` (create once, on first use):

```markdown
# Design invariants (regression guards)
<!-- or: # Verified facts (do not re-investigate) -->

Long-lived, append-only. `wrapup` moves STATE.md's matching section here, dated and
linked to the cycle's archive, before resetting STATE.md.
```

Each cycle's append is a new section:

```markdown
## YYYY-MM-DD — [<slug>](../docs/archive/YYYY-MM-DD-<slug>/)

{the bullet points copied from STATE.md's section, verbatim}
```

`ARCHITECTURE.md` (create once, on first use):

```markdown
# Architecture

Long-lived index. Unlike intent.md/spec.md/design.md/plan.md/STATE.md, this file is
never reset — wrapup appends to it at the end of every cycle.

## Executive overview
{1-2 paragraph description of the system as it currently stands}

## Cycle index

| Date | Slug | Summary | Archive |
|---|---|---|---|
```

## Output artifact

- `docs/archive/YYYY-MM-DD-<slug>/{intent,spec,design,plan}.md` (+ `HANDOFF.md` if it
  existed).
- `ARCHITECTURE.md` with a new cycle-index row (and diagram update if applicable).
- `docs/DESIGN-INVARIANTS.md` / `docs/VERIFIED-FACTS.md` with a new dated section, if
  STATE.md had content to preserve.
- Root `intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md` reset to blank
  templates.
- No worktrees left over from the closed cycle.

## Stop conditions / human gate

- Never assume a PR happened or that it merged — ask the operator (PRs are optional
  here); proceed only once they confirm the cycle's work is actually complete.
- Never delete a worktree with uncommitted or unmerged work without explicit
  confirmation.
- Never reset `STATE.md` without first preserving any non-empty Design
  invariants/Verified facts content into the long-lived docs — that knowledge doesn't
  get a second chance once STATE.md is wiped.
- If asked to also clean up source code, tests, or open a new PR, that's out of scope
  for `wrapup` — say so and point back to the right earlier-stage skill.
