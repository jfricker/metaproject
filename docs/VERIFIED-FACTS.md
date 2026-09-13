# Verified facts (do not re-investigate)

Long-lived, append-only. `wrapup` moves STATE.md's "Verified facts (do not
re-investigate)" section here, dated and linked to the cycle's archive, before
resetting STATE.md. Read this before re-deriving something a prior cycle already
confirmed.

## 2026-09-13 — [create-docs-archive-so-wrapup-has-somewhere-to-archive-into](../docs/archive/2026-09-13-create-docs-archive-so-wrapup-has-somewhere-to-archive-into/)

- Repo's SDLC artifact conventions (intent.md → spec.md → plan.md, STATE.md,
  HANDOFF.md, archive naming `YYYY-MM-DD-<title>`) are defined in `AGENTS.md`.
- Blog playbook fetched from https://claude.com/blog/the-ai-native-sdlc-playbook on
  2026-09-13: 6 stages (Plan/Design/Build/Test/Deploy/Maintain); `design.md` as a
  distinct artifact from `spec.md` is this repo's own extension, anticipated by
  AGENTS.md's plan.md description ("spec.md and any design artifacts").
- No `Makefile` exists yet despite `AGENTS.md`/`CLAUDE.md` referencing `make help` as
  the primary dev/test entry point (confirmed via `make help` failing with "No rule to
  make target `help`" on 2026-09-13).
