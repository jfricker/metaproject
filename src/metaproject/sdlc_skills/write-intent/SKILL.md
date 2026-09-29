---
name: write-intent
description: Start a new SDLC cycle by brainstorming a raw problem statement (an idea, ticket, or incident) into a version-controlled intent.md. Use when the user wants to kick off new work, propose a change, or capture "what we want to build and why" before any spec or code exists. First step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# write-intent

Stage 1 of the SDLC loop: capture intent once, in the originator's own words, as a
version-controlled artifact — before any requirements, design, or code work starts.

## Conventions (metaproject)

- **Session assumption**: a `SessionStart` hook already checked that metaproject ≥
  0.7.0 is installed and `.metaproject.json` exists; this skill doesn't re-check. If
  the session-start `[sdlc-skills]` notice reported a failure, stop and repeat its fix
  instead of proceeding. If a metaproject command fails anyway, stop and show the user
  its output.
- **Documents come from metaproject**: working documents are templated by metaproject,
  not by this skill. Create a missing one with `metaproject backfill <file>`
  (create-only — it never overwrites); `metaproject backfill` with no files creates
  every missing scaffolded deliverable at once. `HANDOFF.md` is on-demand:
  `metaproject backfill HANDOFF.md`.
- **Blank rule**: a cycle document (intent/spec/design/plan) is blank iff its first
  `# ` heading contains `<Title>`.
- **Status vocabulary**: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
  `Superseded`. Header fields are `Author`, `Derived from` (not on intent.md),
  `Last updated`, `Status`, `Approved by`. On approval set `**Status**: Approved.` and
  `**Approved by**: <name> (<YYYY-MM-DD>).`; approval gates check that Status is
  `Approved`. Never set it to `Approved` yourself.
- Tick STATE.md Process item 1 once this stage is done.

## When to use

- The user has a problem statement, idea, ticket, or incident and wants to start work.
- `intent.md` at the repo root is blank per the blank rule above, or missing — if
  missing, run `metaproject backfill intent.md` first, then confirm it's blank.
- Do **not** use this to resume work on an already-approved `intent.md` — that belongs
  to `generate-spec` onward.

## Inputs

- The user's raw description of the problem (however rough).
- `ARCHITECTURE.md` and `docs/VERIFIED-FACTS.md`, if they exist — check them so the
  intent is framed against what's already known about the system, instead of
  rediscovering it.
- The existing `intent.md` template at the repo root (title/author/date/status header,
  Problem / Proposed outcome / Affected users and systems / Scope / Resolved decisions /
  Constraints / Open questions).

## Process

1. **Brainstorm, don't transcribe.** If the `brainstorming` skill is available, load
   its approach; either way, ask questions until the problem, proposed outcome,
   affected systems, and constraints are concrete — don't just restate what the user
   typed.
2. **From the backlog.** If the idea comes from a `docs/backlog/` doc, use that doc as
   the raw problem statement — verify its "Current behavior" still holds, carry its
   Goal and Open questions into intent.md, and flip the doc's Status line to
   `promoted YYYY-MM-DD (<cycle name>)` when the cycle starts.
3. Draft `intent.md` in place, filling every section:
   - **Problem** — what's wrong or missing, for whom.
   - **Proposed outcome** — what "done" looks like, observably.
   - **Affected users and systems** — who/what this touches.
   - **Scope** — In Scope (v1) / Out of Scope (v1), explicit boundaries.
   - **Resolved decisions** — choices already made and why.
   - **Constraints** — technical, timeline, policy.
   - **Open questions** — anything still unresolved; these must be closed (or explicitly
     deferred) before approval.
   - Set **Status** to `Draft` while iterating.
4. Iterate with the user until the doc reads as their own words, not a guess.
5. When the user confirms it's ready, set **Status: Approved** and record the approver.

## Output artifact

`intent.md` at the repo root, status `Approved`.

## Stop conditions / human gate

- Do not flip Status to `Approved` yourself — the product owner (the user, unless they
  name someone else) approves explicitly.
- Do not proceed to `generate-spec` in the same turn unless asked; hand back and let the
  user decide when to move to the next stage.
