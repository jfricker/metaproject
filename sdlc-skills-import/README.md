# sdlc-skills

**Experimental (v0.0.2).** A Claude Code plugin providing seven skills that implement an
agent-centered SDLC loop, adapted from [the AI-native SDLC
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

## Dependency on metaproject

sdlc-skills requires `metaproject` **≥ 0.7.0** on `PATH` and carries no document
templates of its own — every template (`intent.md`, `spec.md`, `design.md`, `plan.md`,
`STATE.md`, `ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`/`docs/VERIFIED-FACTS.md`,
`AGENTS.md`, `README.md`, `CLAUDE.md`, `.gitignore`, `HANDOFF.md`) is owned by
metaproject's central store. A project must be metaproject-managed (identified by a
`.metaproject.json` at its root) for the skills in this plugin to operate on it.

### SessionStart check

The plugin ships a `SessionStart` hook (`hooks/hooks.json` +
`hooks/check-metaproject.sh`) that runs once per session, at the git top-level of the
working directory. It checks:

- `metaproject` is on `PATH` and reports version ≥ 0.7.0;
- `.metaproject.json` exists at the project root.

If both checks pass it prints nothing. Otherwise it prints one short notice naming the
failure and the fix (install or upgrade `metaproject`; or, if the project isn't yet
metaproject-managed, preview with `metaproject new . --dry-run` and have the operator
run `metaproject new .`). The hook is read-only: it never writes files and never blocks
the session — a skill that then runs anyway hits the same check and stops with the
same notice.

### Creating missing documents

If a skill needs a document that doesn't yet exist (a fresh `design.md`, a `HANDOFF.md`
on interruption), it runs `metaproject backfill <file>` to create it from the template
store rather than writing it from scratch. `metaproject backfill` never overwrites an
existing file.

### Making a project metaproject-managed

A project that isn't yet metaproject-managed has no `.metaproject.json`. To bring it
under management:

1. Preview what would be scaffolded: `metaproject new . --dry-run`.
2. Have the operator run `metaproject new .` to actually create `.metaproject.json` and
   any missing governance/working documents.

Agents do not run `metaproject new .` themselves — only the dry-run preview.

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

## Development

Run `make test` to run the plugin's own test suite (currently the `SessionStart` hook
script's shell tests). Run `make help` to see all available targets.

## Documentation

- `AGENTS.md` — the SDLC artifact conventions each skill follows.
- `ARCHITECTURE.md` — long-lived index of every cycle run against this repo.
- `docs/DESIGN-INVARIANTS.md` / `docs/VERIFIED-FACTS.md` — durable knowledge carried
  forward by `wrapup` at the end of each cycle.
- `docs/archive/` — completed cycles' `intent.md`/`spec.md`/`design.md`/`plan.md`.
