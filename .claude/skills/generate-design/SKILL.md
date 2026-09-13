---
name: generate-design
description: Turn an approved spec.md into a technical design.md — affected components, data flow, interfaces, and trade-offs — the design artifact generate-plan consumes alongside spec.md. Use when spec.md is approved and the user wants the technical approach worked out before an implementation plan is written. Third step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-design

Stage 2b of the SDLC loop: the technical-design half of "Requirements & Spec" — kept
separate from `generate-spec` because requirements (what/why) and technical design
(how) are different reviews with different reviewers, and `plan.md` needs both as
distinct inputs (per this repo's `AGENTS.md`).

## When to use

- `spec.md` exists at the repo root with `Status: Approved`.
- The user wants the technical approach (architecture, components, data flow) decided
  before `generate-plan` turns it into an implementation sequence.

## Inputs

- Approved `spec.md`.
- The existing codebase: explore actual patterns and conventions in use (don't design in
  a vacuum) — use `Explore` or direct search tools as needed.

## Process

1. Read `spec.md` in full. Refuse to proceed if its Status isn't `Approved`.
2. If `design.md` doesn't exist at the repo root, create it from the **blank template**
   below.
3. For each requirement in `spec.md`, work out:
   - Affected components/modules and how they change.
   - Data flow / interfaces between them.
   - Alternatives considered and why the chosen approach won.
   - Trade-offs and risks (performance, complexity, migration).
4. Keep this at the technical-design level — no file-by-file task breakdown or
   sequencing; that's `generate-plan`'s job.
5. Set **Status: Draft** while iterating; **Status: Approved** once the user/tech lead
   signs off.

## Blank template (`design.md`)

```markdown
# <Title> — Design

**Author**: {agent/user}.
**Derived from**: spec.md ({date}).
**Last updated**: {date}.
**Status**: Draft.

## Affected components

## Data flow / interfaces

## Alternatives considered

## Trade-offs and risks

## Open questions
```

## Output artifact

`design.md` at the repo root, status `Approved`.

## Stop conditions / human gate

- Never set Status to `Approved` yourself; wait for explicit sign-off.
- Hand back to the user rather than auto-advancing to `generate-plan`.
