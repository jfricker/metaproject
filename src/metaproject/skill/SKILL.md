---
name: metaproject
description: Use the `metaproject` CLI to scaffold, audit, and maintain a project's governance documents — AGENTS.md, CLAUDE.md, STATE.md, HANDOFF.md, intent.md, README.md — from a central template store at ~/.metaproject/templates. Use this skill whenever the user wants to start a new project with SDLC boilerplate, add governance or agent-instruction files to an existing repo ("backfill", "scaffold into this directory"), check whether a project has drifted from their templates ("review", "compliance", "is this project up to date"), promote a recurring pattern across projects into the templates themselves ("learn"), or list and classify the projects on their machine ("universe", "which projects am I working on"). Reach for it even when the user does not say "metaproject" by name — if they ask for an AGENTS.md, a STATE.md, a handoff doc, or ask why a project is missing its standard files, this is the tool that owns those files.
---

# metaproject

`metaproject` keeps one set of governance documents consistent across every project on
the machine. A central template store (`~/.metaproject/templates`) is the source of
truth; individual projects drift away from it as work happens; the CLI's job is to close
that loop — scaffold new projects from the templates, report drift in existing ones, and
promote drift that keeps recurring back into the templates.

Understanding that loop matters more than memorizing flags: almost every question a user
asks about this tool is really "which direction am I moving — templates→project, or
project→templates?"

| Direction | Command | What it does |
|---|---|---|
| templates → new project | `new` | Scaffold a project (or backfill an existing directory) |
| templates ↔ project | `review` | Report what is missing or has drifted; remediate |
| projects → templates | `learn` | Turn recurring drift into reviewed template proposals |
| survey | `universe` | Catalog and classify projects across a workspace tree |
| setup | `init` | Create `~/.metaproject/` (config, template store, catalog) |

## Before anything else: is it installed?

```bash
metaproject --version || echo "not installed"
```

If the command is missing, say so rather than guessing at what it would have done. If
`~/.metaproject/config.json` does not exist, the environment has not been initialized —
`metaproject init` is interactive, so hand that command to the user rather than running
it yourself.

## Running it as an agent

Two commands (`review` and `learn`) open full-screen interactive TUIs when they detect a
terminal. That is right for a human and wrong for you: a TUI in a tool call blocks
waiting for keystrokes that never come, and returns a screenful of escape sequences. Use
the non-interactive forms instead — they exist precisely so automation and humans share
one code path:

```bash
metaproject review --no-tui                # the board, printed, then exits
metaproject learn list                     # proposals as a table
metaproject learn show <id>                # one proposal in full
```

`metaproject new` also prompts unless you supply the values it would ask for. Give it
`--title`, `--description`, and `--author`, or pass `--yes` to accept defaults.

Read-only and safe to run whenever they would help: `review --no-tui`, `universe`,
`learn list`, `learn show`, and any `--dry-run`.

## Scaffolding a new project

```bash
metaproject new rover-api \
  --title "Rover Telemetry API" \
  --description "High-throughput telemetry streaming service" \
  --yes
```

This creates the directory, renders every template into it, and makes an initial git
commit. Add `--dry-run` first if you want to show the user what will appear before
anything is written. `--no-git` skips the repository.

## Backfilling an existing directory

Pointing `new` at a directory that already contains files is a *backfill*. The CLI shows
what is there and asks for two separate confirmations — one to copy the templates in, one
to set up git. Existing files are kept as-is; only the missing template files are written.

Those prompts need a human. `--yes` cannot answer them by design, and `--force` skips
both *and overwrites colliding files*. So:

- Preview it yourself with `--dry-run`, then **give the command to the user to run**:
  ```bash
  metaproject new . --dry-run    # you run this
  metaproject new .              # they run this
  ```
- Only use `--force` if the user explicitly asks for it after you have told them which
  files it would overwrite. Overwriting someone's hand-written `README.md` or `AGENTS.md`
  is exactly the failure this flow exists to prevent.

## Auditing a project against the templates

```bash
metaproject review --no-tui              # this project
metaproject review /path/to/project --no-tui
metaproject review --all --depth 2 --no-tui   # every project under the tree
```

Each project reports one of three states, and the distinction is worth keeping straight
when you summarize:

- `✓ CLEAN` — nothing missing, nothing drifted.
- `~ DRIFTED` — every file is present, but one or more differ from the template.
- `! INCOMPLETE` — a governance file the template defines is absent. Wins over drift.

Drift is not automatically a defect. A project that has grown a genuinely better
`AGENTS.md` is drifted *and correct*; that is the signal `learn` is built to harvest. So
report drift as a finding, not a fault, and ask which direction the user wants to move it
before touching anything.

Remediation lives behind the interactive board (`u` update a drifted file, `d` deploy a
missing one). To apply a fix non-interactively, tell the user what `review` found and let
them run the board, or write the file yourself from the template if that is clearly what
they want.

## Promoting recurring drift into the templates

`learn` is the reflective half of the tool: it collects how projects have actually
diverged, clusters the divergences, scores them by how often and how recently they
recur, and proposes template edits for the operator to accept.

```bash
metaproject learn list                  # pending proposals — safe, read-only
metaproject learn show 7                # rationale, proposed body, contributing projects
```

Two operations deserve real restraint:

- **`learn scan`** gathers evidence from every project and calls a model (`claude -p`) to
  synthesize proposals. It costs time and money, and it sends redacted diffs off the
  machine. Never run it on your own initiative — surface the command and let the user
  decide.
- **`learn apply <id>`** rewrites a template and commits it. That template governs every
  project scaffolded from here on. Read the proposal with `show`, tell the user what it
  would change and why, and let them accept it.

`learn reject <id>` suppresses a proposal by content hash so it stops resurfacing.

## Surveying the machine

```bash
metaproject universe --summary            # counts by classification
metaproject universe --list --all         # everything cataloged, no disk scan
metaproject universe ~/Projects --depth 3 # rescan a tree
metaproject universe --list --format json # for programmatic use
```

Projects are classified by recency (`Active Now`, `Active Near`, `Active Far`, `Idle`,
`Ancient`, `Archived`). This is the right tool when the user asks "what was I working on"
or wants to find a project whose path they have forgotten — much cheaper than walking the
filesystem yourself.

## The documents are the point

Scaffolding the files is the easy half. Their value comes from being kept current while
work happens, and that is your job in every session inside a metaproject-managed repo:

- **`intent.md`** — the problem and desired outcome, written before implementation.
- **`spec.md` / `plan.md`** — what the intent becomes once it is designed and sequenced.
- **`STATE.md`** — the live checklist: phases, design invariants, verified facts. Update
  it as tasks land, not at the end.
- **`HANDOFF.md`** — written when work is interrupted, so the next session (or the next
  person) can resume without re-deriving context.
- **`AGENTS.md` / `CLAUDE.md`** — how to build, test, and work in this repo.

When you finish a meaningful chunk of work in one of these repos, updating `STATE.md`
is part of finishing — not a separate chore to mention and skip.

See `references/documents.md` for what belongs in each file and how the SDLC flow moves
between them.

## Full command surface

`references/commands.md` has every command with its flags, plus copy-paste
non-interactive recipes. Read it when you need a flag this page does not cover.
