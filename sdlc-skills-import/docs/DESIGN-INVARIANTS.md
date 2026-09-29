# Design invariants (regression guards)

Long-lived, append-only. `wrapup` moves STATE.md's "Design invariants (regression
guards)" section here, dated and linked to the cycle's archive, before resetting
STATE.md. Read this before `generate-spec`/`generate-design`/`generate-plan` so an
invariant established in one cycle isn't accidentally violated in the next.

## 2026-09-13 — [create-docs-archive-so-wrapup-has-somewhere-to-archive-into](../docs/archive/2026-09-13-create-docs-archive-so-wrapup-has-somewhere-to-archive-into/)

- `generate-spec`/`generate-design`/`generate-plan` own the canonical blank templates
  for `spec.md`/`design.md`/`plan.md`; `wrapup` must reuse those shapes, not redefine
  them, when it resets the repo root after archiving a cycle.
- `wrapup` only ever touches SDLC documents (`intent.md`/`spec.md`/`design.md`/
  `plan.md`/`HANDOFF.md`/`STATE.md`), `ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`,
  `docs/VERIFIED-FACTS.md`, the `docs/archive/` directory, and git worktree
  bookkeeping — never source code, tests, or PRs.
- PRs are optional in this repo's workflow (`AGENTS.md`); `wrapup` asks the operator
  whether the cycle it's closing used one rather than assuming a merge happened.
