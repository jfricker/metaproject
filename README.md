# sdlc-skills

A Claude Code plugin providing seven skills that implement an agent-centered SDLC loop,
adapted from [the AI-native SDLC
playbook](https://claude.com/blog/the-ai-native-sdlc-playbook):

```
write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup
                                                                                                       │
                                                                                    resets root docs ──┘
```

| Skill | Produces | Purpose |
|---|---|---|
| `write-intent` | `intent.md` | Brainstorm a raw problem statement into an approved intent. |
| `generate-spec` | `spec.md` | Requirements + acceptance criteria, with policy concerns flagged as they're written. |
| `generate-design` | `design.md` | Technical design: affected components, data flow, alternatives, trade-offs. |
| `generate-plan` | `plan.md` | Implementation plan via Claude Code's plan mode — no code until approved. |
| `implement-plan` | code + tests | Executes the approved plan, keeping `STATE.md` current. |
| `execute-tests` | a green run | Self-checks the work (tests/build/lint) before a human reviews it. |
| `wrapup` | archive + reset | Resolves open items with the operator, archives the cycle, updates the long-lived docs, resets the root docs for the next cycle. |

Each stage gates on the previous one's approval and hands off a version-controlled
artifact — see `AGENTS.md` for the full artifact conventions (`intent.md`, `spec.md`,
`design.md`, `plan.md`, `STATE.md`, `HANDOFF.md`) and the long-lived docs `wrapup`
maintains (`ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`).

## Install

From inside Claude Code, in any project you want the cycle available in:

```
/plugin marketplace add <path-or-url-to-this-repo>
/plugin install sdlc-skills
```

`<path-or-url-to-this-repo>` is a local path (e.g. `/plugin marketplace add .` when run
from a checkout of this repo) or this repo's git URL once it's hosted remotely. Once
installed, the seven skills above are available via the `Skill` tool in that project,
same as any other plugin skill.

## Using it on this repo itself

This repo dogfoods its own plugin: install it (as above, `/plugin marketplace add .`
from a checkout) to get `write-intent`/`generate-spec`/etc. available here too, the same
way any consumer project would.

## Documentation

- `AGENTS.md` — the SDLC artifact conventions each skill follows.
- `ARCHITECTURE.md` — long-lived index of every cycle run against this repo.
- `docs/DESIGN-INVARIANTS.md` / `docs/VERIFIED-FACTS.md` — durable knowledge carried
  forward by `wrapup` at the end of each cycle.
- `docs/archive/` — completed cycles' `intent.md`/`spec.md`/`design.md`/`plan.md`.
