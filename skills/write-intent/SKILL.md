---
name: write-intent
description: Start a new SDLC cycle by brainstorming a raw problem statement (an idea, ticket, or incident) into a version-controlled intent.md. Use when the user wants to kick off new work, propose a change, or capture "what we want to build and why" before any spec or code exists. First step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# write-intent

Stage 1 of the SDLC loop (`docs`/`AGENTS.md`): capture intent once, in the
originator's own words, as a version-controlled artifact — before any requirements,
design, or code work starts.

## When to use

- The user has a problem statement, idea, ticket, or incident and wants to start work.
- `intent.md` at the repo root is currently blank/templated (no active cycle in flight).
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

1. **Brainstorm, don't transcribe.** Load the `brainstorming` skill's approach: ask
   questions until the problem, proposed outcome, affected systems, and constraints are
   concrete — don't just restate what the user typed.
2. Draft `intent.md` in place, filling every section:
   - **Problem** — what's wrong or missing, for whom.
   - **Proposed outcome** — what "done" looks like, observably.
   - **Affected users and systems** — who/what this touches.
   - **Scope** — In Scope (v1) / Out of Scope (v1), explicit boundaries.
   - **Resolved decisions** — choices already made and why.
   - **Constraints** — technical, timeline, policy.
   - **Open questions** — anything still unresolved; these must be closed (or explicitly
     deferred) before approval.
   - Set **Status** to `Draft` while iterating.
3. Iterate with the user until the doc reads as their own words, not a guess.
4. When the user confirms it's ready, set **Status: Approved** and record the approver.

## Output artifact

`intent.md` at the repo root, status `Approved`.

## Stop conditions / human gate

- Do not flip Status to `Approved` yourself — the product owner (the user, unless they
  name someone else) approves explicitly.
- Do not proceed to `generate-spec` in the same turn unless asked; hand back and let the
  user decide when to move to the next stage.
