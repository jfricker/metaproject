---
name: generate-spec
description: Turn an approved intent.md into a requirements/design spec.md, applying any organization policy skills (security, compliance, brand, UX) as it's written and flagging concerns for the product owner to resolve. Use when intent.md is approved and the user wants requirements defined before design or planning starts. Second step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-spec

Stage 2a of the SDLC loop: policy is applied while the spec is written, not discovered
in a review weeks later.

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
- Tick STATE.md Process item 2 once this stage is done.

## When to use

- `intent.md` exists at the repo root with `Status: Approved`.
- The user wants requirements/acceptance criteria defined before `generate-design` or
  `generate-plan`.

## Inputs

- Approved `intent.md`.
- `docs/VERIFIED-FACTS.md` and `docs/DESIGN-INVARIANTS.md`, if they exist — a fact or
  invariant recorded there from a prior cycle doesn't need re-investigating or
  re-deriving here.
- Any available organization/policy skills relevant to the change (security, compliance,
  brand, UX, accessibility) — check the available-skills listing and load ones that
  apply before writing requirements, so policy shapes the spec instead of being
  discovered later.

## Process

1. Read `intent.md` in full. Refuse to proceed (tell the user) if its Status isn't
   `Approved`.
2. If `spec.md` doesn't exist at the repo root, create it with
   `metaproject backfill spec.md`. If it exists but isn't blank (per the blank rule)
   and its **Derived from** doesn't reference the current `intent.md`, that's a stale
   spec from a prior cycle — tell the user rather than overwriting silently.
3. For each item in intent.md's Scope, derive concrete, testable requirements —
   functional and non-functional (performance, security, accessibility as relevant).
4. Write acceptance criteria a human or `execute-tests` could later check against.
5. Apply any loaded policy skills as you write; where a requirement conflicts with
   policy or is ambiguous, add it to **Flagged concerns** instead of guessing.
6. Set **Status: Draft** while iterating with the user; **Status: Approved** once the
   product owner has resolved all flagged concerns (with policy owners, if named).

## Output artifact

`spec.md` at the repo root, status `Approved`, all flagged concerns resolved or
explicitly deferred.

## Stop conditions / human gate

- Never set Status to `Approved` while **Flagged concerns** has unresolved items.
- Hand back to the user rather than auto-advancing to `generate-design`.
