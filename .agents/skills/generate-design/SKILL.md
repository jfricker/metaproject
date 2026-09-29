---
name: generate-design
description: Turn an approved SPEC.md into a technical TECH-DESIGN.md — affected components, data flow, interfaces, and trade-offs — the design artifact generate-plan consumes alongside SPEC.md. Use when SPEC.md is approved and the user wants the technical approach worked out before an implementation plan is written. Third step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-design

> **Precondition.** This project must be metaproject-managed: `.metaproject.json` at the
> repository root and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Stage 2b of the SDLC loop: the technical-design half of "Requirements & Spec" — kept
separate from `generate-spec` because requirements (what/why) and technical design
(how) are different reviews with different reviewers, and `docs/PLAN.md` needs both as
distinct inputs (per this repo's `AGENTS.md`).

## Conventions (metaproject)

- **Documents come from metaproject**: working documents are templated by metaproject,
  not by this skill, and live in `docs/` (`docs/INTENT.md`, `docs/SPEC.md`,
  `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`, `docs/ARCHITECTURE.md`).
  Create a missing one with `metaproject backfill docs/<FILE>.md` (create-only — it
  never overwrites); `metaproject backfill` with no files creates every missing
  scaffolded deliverable at once. `docs/HANDOFF.md` is on-demand:
  `metaproject backfill docs/HANDOFF.md`.
- If a metaproject command fails, stop and show the user its output.
- **Blank rule**: a cycle document (INTENT/SPEC/TECH-DESIGN/PLAN) is blank iff its first
  `# ` heading contains `<Title>`.
- **Status vocabulary**: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
  `Superseded`. Header fields are `Author`, `Derived from` (not on INTENT.md),
  `Last updated`, `Status`, `Approved by`. On approval set `**Status**: Approved.` and
  `**Approved by**: <name> (<YYYY-MM-DD>).`; approval gates check that Status is
  `Approved`. Never set it to `Approved` yourself.
- Tick `docs/STATE.md` Process item 3 once this stage is done.

## When to use

- `docs/SPEC.md` exists with `Status: Approved`.
- The user wants the technical approach (architecture, components, data flow) decided
  before `generate-plan` turns it into an implementation sequence.

## Inputs

- Approved `docs/SPEC.md`.
- `docs/ARCHITECTURE.md` and `docs/DESIGN-INVARIANTS.md`, if they exist — read them first so
  the design fits the system's established structure and doesn't violate an invariant
  a prior cycle already settled.
- The existing codebase: explore actual patterns and conventions in use (don't design in
  a vacuum) — use `Explore` or direct search tools as needed.

## Process

1. Read `docs/SPEC.md` in full. Refuse to proceed if its Status isn't `Approved`.
2. If `docs/TECH-DESIGN.md` doesn't exist, create it with
   `metaproject backfill docs/TECH-DESIGN.md`.
3. For each requirement in `docs/SPEC.md`, work out:
   - Affected components/modules and how they change.
   - Data flow / interfaces between them.
   - Alternatives considered and why the chosen approach won.
   - Trade-offs and risks (performance, complexity, migration).
4. Keep this at the technical-design level — no file-by-file task breakdown or
   sequencing; that's `generate-plan`'s job.
5. Set **Status: Draft** while iterating; **Status: Approved** once the user/tech lead
   signs off.

## Output artifact

`docs/TECH-DESIGN.md`, status `Approved`.

## Stop conditions / human gate

- Never set Status to `Approved` yourself; wait for explicit sign-off.
- Hand back to the user rather than auto-advancing to `generate-plan`.
