---
name: generate-spec
description: Turn an approved INTENT.md into a requirements/design SPEC.md, applying any organization policy skills (security, compliance, brand, UX) as it's written and flagging concerns for the product owner to resolve. Use when INTENT.md is approved and the user wants requirements defined before design or planning starts. Second step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-spec

> **Precondition.** This project must be metaproject-managed: `.metaproject.json` at the
> repository root and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Stage 2a of the SDLC loop: policy is applied while the spec is written, not discovered
in a review weeks later.

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
- Tick `docs/STATE.md` Process item 2 once this stage is done.

## When to use

- `docs/INTENT.md` exists with `Status: Approved`.
- The user wants requirements/acceptance criteria defined before `generate-design` or
  `generate-plan`.

## Inputs

- Approved `docs/INTENT.md`.
- `docs/VERIFIED-FACTS.md` and `docs/DESIGN-INVARIANTS.md`, if they exist — a fact or
  invariant recorded there from a prior cycle doesn't need re-investigating or
  re-deriving here.
- Any available organization/policy skills relevant to the change (security, compliance,
  brand, UX, accessibility) — check the available-skills listing and load ones that
  apply before writing requirements, so policy shapes the spec instead of being
  discovered later.

## Process

1. Read `docs/INTENT.md` in full. Refuse to proceed (tell the user) if its Status isn't
   `Approved`.
2. If `docs/SPEC.md` doesn't exist, create it with
   `metaproject backfill docs/SPEC.md`. If it exists but isn't blank (per the blank rule)
   and its **Derived from** doesn't reference the current `docs/INTENT.md`, that's a stale
   spec from a prior cycle — tell the user rather than overwriting silently.
3. For each item in INTENT.md's Scope, derive concrete, testable requirements —
   functional and non-functional (performance, security, accessibility as relevant).
4. Write acceptance criteria a human or `execute-tests` could later check against.
5. Apply any loaded policy skills as you write; where a requirement conflicts with
   policy or is ambiguous, add it to **Flagged concerns** instead of guessing.
6. Set **Status: Draft** while iterating with the user; **Status: Approved** once the
   product owner has resolved all flagged concerns (with policy owners, if named).

## Output artifact

`docs/SPEC.md`, status `Approved`, all flagged concerns resolved or
explicitly deferred.

## Stop conditions / human gate

- Never set Status to `Approved` while **Flagged concerns** has unresolved items.
- Hand back to the user rather than auto-advancing to `generate-design`.
