---
name: generate-spec
description: Turn an approved intent.md into a requirements/design spec.md, applying any organization policy skills (security, compliance, brand, UX) as it's written and flagging concerns for the product owner to resolve. Use when intent.md is approved and the user wants requirements defined before design or planning starts. Second step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-spec

Stage 2a of the SDLC loop: policy is applied while the spec is written, not discovered
in a review weeks later.

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
2. If `spec.md` doesn't exist at the repo root, create it from the **blank template**
   below. If it exists and is a stale spec from a prior cycle, that's a `wrapup` bug —
   tell the user rather than overwriting silently.
3. For each item in intent.md's Scope, derive concrete, testable requirements —
   functional and non-functional (performance, security, accessibility as relevant).
4. Write acceptance criteria a human or `execute-tests` could later check against.
5. Apply any loaded policy skills as you write; where a requirement conflicts with
   policy or is ambiguous, add it to **Flagged concerns** instead of guessing.
6. Set **Status: Draft** while iterating with the user; **Status: Approved** once the
   product owner has resolved all flagged concerns (with policy owners, if named).

## Blank template (`spec.md`)

```markdown
# <Title> — Spec

**Author**: {agent/user}.
**Derived from**: intent.md ({date}).
**Last updated**: {date}.
**Status**: Draft.

## Requirements

### Functional

### Non-functional

## Acceptance criteria

## Flagged concerns
{Policy/security/compliance/UX concerns needing product-owner or policy-owner resolution}

## Open questions
```

## Output artifact

`spec.md` at the repo root, status `Approved`, all flagged concerns resolved or
explicitly deferred.

## Stop conditions / human gate

- Never set Status to `Approved` while **Flagged concerns** has unresolved items.
- Hand back to the user rather than auto-advancing to `generate-design`.
