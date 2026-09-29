---
name: generate-design
description: Turn an approved spec.md into a technical design.md — affected components, data flow, interfaces, and trade-offs — the design artifact generate-plan consumes alongside spec.md. Use when spec.md is approved and the user wants the technical approach worked out before an implementation plan is written. Third step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-design

Stage 2b of the SDLC loop: the technical-design half of "Requirements & Spec" — kept
separate from `generate-spec` because requirements (what/why) and technical design
(how) are different reviews with different reviewers, and `plan.md` needs both as
distinct inputs (per this repo's `AGENTS.md`).

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
- Tick STATE.md Process item 3 once this stage is done.

## When to use

- `spec.md` exists at the repo root with `Status: Approved`.
- The user wants the technical approach (architecture, components, data flow) decided
  before `generate-plan` turns it into an implementation sequence.

## Inputs

- Approved `spec.md`.
- `ARCHITECTURE.md` and `docs/DESIGN-INVARIANTS.md`, if they exist — read them first so
  the design fits the system's established structure and doesn't violate an invariant
  a prior cycle already settled.
- The existing codebase: explore actual patterns and conventions in use (don't design in
  a vacuum) — use `Explore` or direct search tools as needed.

## Process

1. Read `spec.md` in full. Refuse to proceed if its Status isn't `Approved`.
2. If `design.md` doesn't exist at the repo root, create it with
   `metaproject backfill design.md`.
3. For each requirement in `spec.md`, work out:
   - Affected components/modules and how they change.
   - Data flow / interfaces between them.
   - Alternatives considered and why the chosen approach won.
   - Trade-offs and risks (performance, complexity, migration).
4. Keep this at the technical-design level — no file-by-file task breakdown or
   sequencing; that's `generate-plan`'s job.
5. Set **Status: Draft** while iterating; **Status: Approved** once the user/tech lead
   signs off.

## Output artifact

`design.md` at the repo root, status `Approved`.

## Stop conditions / human gate

- Never set Status to `Approved` yourself; wait for explicit sign-off.
- Hand back to the user rather than auto-advancing to `generate-plan`.
