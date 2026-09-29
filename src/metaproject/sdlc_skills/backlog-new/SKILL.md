---
name: backlog-new
description: Capture an idea that is NOT ready to become an SDLC cycle — brainstorm it with the user and park the result as docs/backlog/<slug>.md. Use when the user says "new backlog", "backlog-new", "park this idea", "add to backlog", "save this for later", or wants to brainstorm a direction without starting work. Not for work starting now — that is write-intent.
---

# backlog-new

Pre-cycle idea parking lot: brainstorm an idea the user does not want to start yet and
distill the session into a version-controlled backlog doc. The 7-stage cycle starts at
`write-intent`; this skill sits before it and is not a cycle stage — it does not touch
`intent.md`, `STATE.md`, or the Process list.

## When to use

- The user has an idea, question, or direction they explicitly want to capture for
  later — not start now. If they want to start now, that's `write-intent`.
- Promoting an existing backlog doc into a cycle is `write-intent`'s job, not this
  skill's (see write-intent's "From the backlog" step).

## Inputs

- The user's raw description of the idea (however rough).
- `ARCHITECTURE.md` and `docs/VERIFIED-FACTS.md`, if they exist — frame the idea
  against what's already known instead of rediscovering it.
- Existing docs in `docs/backlog/`, if any — avoid duplicating a parked idea; extend
  the existing doc instead of writing a second one.

## Process

1. **Brainstorm, don't transcribe.** If the `brainstorming` skill is available, invoke
   it and run its questioning/refinement flow — but override its terminal state: stop
   before any spec file, implementation plan, or code. If it is not installed, run this
   loop yourself:
   - Classify the idea: quick capture vs. needs exploration.
   - Ask clarifying questions one at a time until the goal and direction are concrete
     enough that a future session could pick the doc up cold.
   - Explore repo context as needed to ground "current behavior" in facts.
2. **Distill, don't dump.** Compress the session into the doc format below — decisions
   and rationale, not transcript.
3. Write `docs/backlog/<kebab-slug>.md` (create the directory if missing). Slug from
   the idea's short name; show the user the path.
4. Commit the doc on the current branch with a `docs(backlog): <slug>` message.

## Output artifact

`docs/backlog/<kebab-slug>.md`, committed, using this format:

```markdown
# <Title>

**Captured**: YYYY-MM-DD[, <triggering context>]
**Status**: backlog — not specced, not scheduled.
**Target**: <repo/system this would change>

## Goal

<One paragraph: what problem or opportunity, for whom.>

## Current behavior (verified YYYY-MM-DD)

<How the system behaves today, grounded in what was checked — files, docs, commands.>

## Proposed direction

<The direction the session converged on, with the rationale for decisions made.>

## Open questions

<What a future cycle must resolve before speccing. May be empty.>
```

The Status line changes only via promotion: when `write-intent` starts a cycle from
this doc it flips Status to `promoted YYYY-MM-DD (<cycle name>)` and leaves the doc in
place.

## Stop conditions / human gate

- Do not create or modify cycle documents (`intent.md`, `spec.md`, `design.md`,
  `plan.md`, `STATE.md`) — this skill never starts a cycle.
- Do not implement anything the session dreamed up; the doc is the only artifact.
- If the session reveals the user actually wants to start now, stop and hand off to
  `write-intent` (which can consume this doc once written).
