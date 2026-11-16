---
name: wrapup
description: End-of-cycle archive and reset. First resolves STATE.md's Open items with the operator (discard, carry forward, or send the cycle back to implement-plan), then marks INTENT.md Complete, appends STATE.md's Design invariants and Verified facts to the long-lived docs, updates ARCHITECTURE.md's cycle index, archives the cycle documents into docs/archive/, flags unrelated changes that would ship, hands branch and worktree cleanup to `/shipit` (with a manual fallback), and recreates blank cycle documents with `metaproject backfill`. Besides documents it changes only git worktrees and the cycle's local and remote branches; never source code or tests. Records everything it could not verify itself in docs/TODO.md. Use when the user says the current cycle is finished and ready to close out. Final step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# wrapup

> **Precondition.** This project must be metaproject-managed: the nearest `.metaproject.json`
> (this directory or an ancestor) and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Closes the loop: once a cycle's work is done, archive everything it produced, preserve
what's worth keeping long-term, and reset `docs/` to a blank slate for the next
`write-intent`.

## Conventions (metaproject)

- **Documents come from metaproject**: working documents are templated by metaproject,
  not by this skill, and live in `docs/` (`docs/INTENT.md`, `docs/SPEC.md`,
  `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`, `docs/ARCHITECTURE.md`).
  Create a missing one with `metaproject backfill docs/<FILE>.md` (create-only — it
  never overwrites); `metaproject backfill` with no files creates every missing
  scaffolded deliverable at once. `docs/HANDOFF.md` is on-demand:
  `metaproject backfill docs/HANDOFF.md`. `docs/TODO.md` is on-demand too
  (`metaproject backfill docs/TODO.md`).
- If a metaproject command fails, stop and show the user its output.
- **Blank rule**: a cycle document (INTENT/SPEC/TECH-DESIGN/PLAN) is blank iff its first
  `# ` heading contains `<Title>`.
- **Status vocabulary**: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
  `Superseded`. Header fields are `Author`, `Derived from` (not on INTENT.md),
  `Last updated`, `Status`, `Approved by`. On approval set `**Status**: Approved.` and
  `**Approved by**: <name> (<YYYY-MM-DD>).`; approval gates check that Status is
  `Approved`. Set `Approved` only on the operator's explicit sign-off, never on your
  own judgment.
- Tick `docs/STATE.md` Process item 7 once this stage is done (before it's archived — see
  Process below).

**Scope discipline**: this skill only ever touches SDLC documents (`docs/INTENT.md`,
`docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/HANDOFF.md`, `docs/STATE.md`), `docs/TODO.md` (append-only), the long-lived docs
(`docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`), the
`docs/archive/` directory, and git worktree bookkeeping. It never edits source code,
tests, or opens a PR — if any of those are still outstanding, the cycle isn't done; send
the user back to `execute-tests`/`implement-plan` instead of running `wrapup`.

## When to use

- The user says the current cycle's work is finished and ready to close out.
- `docs/INTENT.md` shows `Status: Approved` and the work it describes is
  actually done — don't archive an in-flight or abandoned cycle without confirming with
  the user first.

## Inputs

- The current `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/HANDOFF.md` (if present),
  and `docs/STATE.md`.
- `docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md` — if any is
  missing, create it with `metaproject backfill docs/<FILE>.md` before appending to it.
- `git worktree list` for any worktrees created during this cycle.

## Process

1. Confirm with the user which cycle is being closed if it's at all ambiguous (more than
   one `docs/INTENT.md`-shaped thing could be meant).
2. **Resolve STATE.md's "Open items carried into PLAN.md" before anything else — this
   can abort the whole wrapup, so do it before touching any file.**
   - If the section is empty, skip to step 3.
   - If it has content, for each item work out *why it's still open*: check whether
     `docs/PLAN.md`/`implement-plan`'s actual work addressed it, whether `execute-tests`
     touched it, or whether it was never picked up at all. Don't just relay the raw
     text — show the operator the item plus your assessment of its status.
   - Ask the operator, per item, to choose one:
     - **Discard** — no longer relevant; drop it.
     - **Carry forward** — it's real but out of scope for this cycle; it gets seeded
       into the next `docs/INTENT.md`'s Open questions section (step 8), linked back to this
       cycle's archive, so `write-intent` starts the next cycle with it already in view.
     - **Return to implement-plan** — the cycle isn't actually finished; this item needs
       real work, not a note. If the operator picks this for *any* item, **stop the
       entire wrapup run here** — archive nothing, reset nothing, hand back to
       `implement-plan` instead.
   - Only proceed past this step once every item has a discard/carry-forward decision
     (or the return-to-implement-plan exit has already happened).
3. **PRs are optional in this workflow (per `AGENTS.md`) — don't assume either way.**
   Ask the operator whether this cycle went through a PR:
   - If yes, verify it's merged before continuing.
   - If no, get explicit confirmation from the operator that the cycle's work is
     finished and committed (to `main` or wherever they're closing it from).
   Do not archive/reset until this is confirmed one way or the other.
4. Set `docs/INTENT.md`'s `**Status**: Complete.` (it was `Approved`; the cycle it approved
   is now done) before archiving it.
5. Derive an archive slug from `docs/INTENT.md`'s title and today's date:
   `docs/archive/YYYY-MM-DD-<slugified-title>/`.
6. **Preserve long-lived knowledge before STATE.md is archived:**
   - If STATE.md's **Design invariants (regression guards)** section has content,
     append it to `docs/DESIGN-INVARIANTS.md` under a new dated heading linking to this
     cycle's archive directory. Skip if the section is empty.
   - If STATE.md's **Verified facts (do not re-investigate)** section has content,
     append it to `docs/VERIFIED-FACTS.md` the same way. Skip if empty.
   - Add a row to `docs/ARCHITECTURE.md`'s cycle index: date, slug, a one/two-line summary of
     what the cycle did, links to the archived
     `docs/archive/YYYY-MM-DD-<slug>/SPEC.md` and `…/TECH-DESIGN.md`. If `docs/TECH-DESIGN.md`'s
     Affected components / Data flow sections describe a structural change, amend
     `docs/ARCHITECTURE.md`'s existing mermaid diagram(s) to reflect it — update in place,
     don't regenerate from scratch each cycle.
7. Confirm `docs/archive/` already exists and is tracked (`git ls-files docs/archive/`
   should list at least `docs/archive/.gitkeep`) — this is a precondition of the repo,
   not something this step creates. If it's missing, fix it with
   `metaproject backfill docs/archive` rather than `mkdir -p`-ing it into existence.
   Once confirmed, `git mv` (or move + `git add`) each of `docs/INTENT.md`, `docs/SPEC.md`,
   `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`, and `docs/HANDOFF.md` (if present) into the derived
   archive directory, preserving history. If INTENT.md has an `**Origin**` field pointing
   at a `docs/backlog/` doc, `git mv` that doc into the archive directory too. STATE.md is
   archived whole, only after step 6 has already copied its invariants/facts elsewhere.
8. Recreate the working documents in `docs/` in one call:
   `metaproject backfill` (no file arguments) — this recreates blank `docs/INTENT.md`,
   `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, and `docs/STATE.md` since step 7 moved all of them out.
   Then, if step 2 produced any "carry forward" items, seed the new `docs/INTENT.md`'s
   **Open questions** section with them, each one linked back to the cycle it came from
   (`docs/archive/YYYY-MM-DD-<slug>/`).
9. **Record what you could not verify, then commit.** Append a dated
   `## YYYY-MM-DD: Needs manual verification (<slug>)` entry to `docs/TODO.md`; if the
   file is missing, create it first with `metaproject backfill docs/TODO.md`. List
   everything this cycle needed but you could not check yourself (browsers, devices, CI
   runs, third-party widgets, deployed environments) as `- [ ]` items, each with the
   exact steps for the operator to check it and the expected result. If there is
   nothing, add the entry anyway with "Nothing outstanding." `docs/TODO.md` is never
   archived or reset. Then commit the archive + long-lived doc updates + `docs/TODO.md`
   entry + reset as one commit on the cycle branch (before the `/shipit` handoff, so the gate and merge carry it to `main`) (e.g.
   `chore: archive <slug> cycle, reset SDLC docs`).
10. **Wrap up the cycle's branch and worktrees** (only after step 9's commit, so the archive and reset ship with the merge). A branch is *wrapped up* when its work
   has passed the gate, been fast-forward merged to `main`, pushed, deployed and
   verified (where the project deploys), and its worktree and local and remote branch
   are gone. Wrapup owns the documents; `/shipit` owns that sequence.
   - **Flag unrelated changes first.** Compare what would land on `main` with this
     cycle's scope: `git log --oneline main..<branch>`, `git diff --stat main...<branch>`,
     and `git status --short` on `main`. List anything that is not part of the cycle
     (held-back dependency upgrades, lockfile churn, stray local commits, other
     people's unpushed work) and ask the operator whether it ships with the push, is
     split out, or is left behind. Never push it silently.
   - **Hand off to `/shipit`** (gate, fast-forward merge to `main`, push, deploy and
     verify, remove the worktree and the local and remote branch) for each worktree
     under `.claude/worktrees/` that belongs to this cycle. Do not duplicate those
     steps here.
   - **Fallback if `/shipit` is not installed** (`.agents/skills/shipit/` is absent):
     for each such worktree, confirm the work is merged (`git branch --merged main` lists the branch); if it is not merged, stop and report to the operator instead of removing anything. Otherwise run `git worktree remove <path>`
     (add `--force` only after confirming with the user there is nothing uncommitted
     worth keeping), then delete the merged branch with `git branch -d <branch>` (and
     `git push origin --delete <branch>` if it exists on the remote). `-d` refuses an
     unmerged branch; never use `-D` without the operator's say-so. Tell the operator
     that merge, push and deploy were not done by this skill.

## Output artifact

- Either: a completed wrapup —
  - `docs/archive/YYYY-MM-DD-<slug>/{INTENT,SPEC,TECH-DESIGN,PLAN,STATE}.md` (+ `…/HANDOFF.md`
    if it existed, + the promoted backlog doc if INTENT.md had an `**Origin**`).
  - `docs/ARCHITECTURE.md` with a new cycle-index row (and diagram update if applicable).
  - `docs/DESIGN-INVARIANTS.md` / `docs/VERIFIED-FACTS.md` with a new dated section, if
    STATE.md had content to preserve.
  - `docs/INTENT.md` (Open questions possibly seeded with carried-forward items),
    `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md` recreated via
    `metaproject backfill`.
  - `docs/TODO.md` with a new dated "Needs manual verification" entry, committed with the archive.
  - No worktrees or merged branches left over from the closed cycle.
- Or: an early exit back to `implement-plan` — nothing archived, nothing reset,
  triggered by the operator choosing "return to implement-plan" on an open item in
  step 2.

## Stop conditions / human gate

- Never resolve STATE.md's Open items yourself — every item gets an explicit
  discard/carry-forward/return-to-implement-plan decision from the operator, and a
  single "return to implement-plan" halts the whole run before anything is touched.
- Never assume a PR happened or that it merged — ask the operator (PRs are optional
  here); proceed only once they confirm the cycle's work is actually complete.
- Never delete a worktree with uncommitted or unmerged work without explicit
  confirmation.
- Never claim something was verified that you did not verify; anything unverified goes
  into the `docs/TODO.md` entry (step 9) with exact steps. Never archive `docs/TODO.md`.
- Never push unrelated changes (step 10) without the operator's explicit say-so.
- Never archive STATE.md without first preserving any non-empty Design
  invariants/Verified facts content into the long-lived docs — that knowledge doesn't
  get a second chance once STATE.md is moved out.
- If asked to also clean up source code, tests, or open a new PR, that's out of scope
  for `wrapup` — say so and point back to the right earlier-stage skill.
