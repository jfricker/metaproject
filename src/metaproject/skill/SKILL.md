---
name: metaproject
description: Use the `metaproject` CLI to scaffold, audit, and maintain a project's SDLC documents — docs/INTENT.md, docs/SPEC.md, docs/TECH-DESIGN.md, docs/PLAN.md, docs/STATE.md, docs/HANDOFF.md, AGENTS.md, CLAUDE.md, README.md — and its project skills from a central template store at ~/.metaproject/templates. Use this skill whenever the user wants to start a new project with SDLC boilerplate, add missing documents to a repo ("backfill", "scaffold into this directory"), check whether a project has drifted from their templates ("review", "compliance", "is this project up to date"), migrate an older project whose cycle documents still sit at its root ("doctor"), promote a recurring pattern across projects into the templates themselves ("learn"), or list and classify the projects on their machine ("universe", "which projects am I working on"). Reach for it even when the user does not say "metaproject" by name — if they ask for an AGENTS.md, a STATE.md, a spec, a handoff doc, or ask why a project is missing its standard files, this is the tool that owns those files.
---

# metaproject

`metaproject` keeps one set of SDLC documents consistent across every project on the
machine. A central template store (`~/.metaproject/templates`) is the source of truth;
individual projects drift away from it as work happens; the CLI's job is to close that
loop — scaffold new projects from the templates, report drift in existing ones, and
promote drift that keeps recurring back into the templates.

Understanding that loop matters more than memorizing flags: almost every question a user
asks about this tool is really "which direction am I moving — templates→project, or
project→templates?"

| Direction | Command | What it does |
|---|---|---|
| templates → new project | `new` | Scaffold a project (or scaffold into an existing directory) |
| templates → existing project | `backfill` | Create specific missing documents, agent-safe |
| templates ↔ project | `review` | Report what is missing or has drifted; remediate |
| projects → templates | `learn` | Turn recurring drift into reviewed template proposals |
| survey | `universe` | Catalog and classify projects across a workspace tree |
| setup | `init` | Create `~/.metaproject/` (config, template store, catalog) |
| repair / migrate | `doctor` | Bring the store, config and cataloged projects up to this release |

## The 7-stage cycle

Every project's documents move through one cycle, each stage owned by a project skill
and ticked off in `docs/STATE.md`'s Process list. The skills ship in the metaproject
wheel; `new` and `backfill` copy them into the project's `.agents/skills/` (reachable as
`.claude/skills/`), where they are committed with the project and invoked by bare name
(`/write-intent`, `/generate-spec`, …, plus `/backlog-new` for parking ideas):

```
write-intent → generate-spec → generate-design → generate-plan →
implement-plan → execute-tests → wrapup
```

All cycle documents live in `docs/`: `INTENT.md` (why), `SPEC.md` (what),
`TECH-DESIGN.md` (how, technically), `PLAN.md` (how, in sequence), then implementation and its tests, then `wrapup` archives the cycle's
documents and resets for the next one. `metaproject` scaffolds and checks the documents;
it does not run the cycle itself.

## Deliverable classes

Every file `metaproject` scaffolds, reviews, or learns from belongs to exactly one class:

- **governance** — `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`. Rendered and
  diffed body-for-body; offered for both Update and Deploy when drifted or missing.
- **working** — `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`,
  `docs/STATE.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`,
  `docs/VERIFIED-FACTS.md`. Checked for
  heading structure only — a template heading with no matching heading in the project
  file is drift — never body-for-body, and never offered for Update; you fill their
  content freely as the cycle runs.
- **on-demand** — `docs/HANDOFF.md`. Never scaffolded by `new` and never reported missing
  by `review`; create it (with `backfill docs/HANDOFF.md`) only when work is interrupted.
- **directory** — `docs/`, `docs/archive/`. Presence checks, nothing more.

## Project identity: `.metaproject.json`

`new` writes `.metaproject.json` at the project root — `title`, `description`, `author`,
`created`, `metaproject_version` — and it is tracked in git. Every other command
(`review`, `learn`, `backfill`, `universe`) reads it first for variable resolution;
without it they fall back to `README.md`, then `pyproject.toml`, then `package.json`,
then the directory name. `metaproject_version` records which version last brought the
project up to date; `new` sets it, and `doctor` when it backfills a missing anchor.
`.metaproject.json` is never itself reviewed or diffed — its absence is an informational
note, not a defect.

## The blank rule

A cycle document (`docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`,
`docs/PLAN.md`) is **blank** iff its
first `# ` heading still contains `<Title>`. This is the one rule every skill and tool
uses to decide "has this been written yet" — `write-intent`'s precondition,
`generate-spec`'s stale-spec check, `wrapup`'s reset. `docs/ARCHITECTURE.md` and the two
long-lived `docs/` files use a different, never-blank header and don't participate.

## Before anything else: is it installed?

```bash
metaproject --version || echo "not installed"
```

If the command is missing, say so rather than guessing at what it would have done. If
`~/.metaproject/config.json` does not exist, the environment has not been initialized —
`metaproject init` is interactive, so hand that command to the user rather than running
it yourself.

## Running it as an agent

The CLI can tell that an agent is driving it — Claude Code and similar harnesses set
markers like `CLAUDECODE` and `AI_AGENT` in the environment — and it changes its own
behavior accordingly. You do not have to remember to be careful; the guards are in the
tool. What you do need is to recognize what they are telling you when they fire.

**The interactive TUIs never open.** `review` and `learn`'s acceptance loop print their
board or table and exit instead, with a line saying so. This is not a failure and the
exit code is zero — a full-screen loop inside a tool call would block on keystrokes that
never arrive. `--no-tui` does the same thing explicitly and is still worth passing when
you want the intent on the record.

**`learn scan` is refused outright**, with exit code 1. It reads every project, calls a
model, and sends redacted diffs off the machine; spending the operator's money and
egressing their code is their decision. The refusal prints the exact command to hand
over — pass it on rather than trying to work around it. Proposals already recorded stay
readable through `learn list` and `learn show`, so there is usually still something
useful you can do.

**Scaffolding into an existing directory (`new .` on a non-empty directory) is
refused** for the same reason: its two confirmations need a person. `--dry-run` still
previews it, which is how you show the operator what would happen. `metaproject
backfill` is the agent-safe alternative for filling in specific missing documents — see
below.

When a guard fires, relay it — "this needs you to run it, here is the command" —
instead of reaching for `--force` or `METAPROJECT_AGENT=0`. Those exist for the
operator, not for you; using them is how an agent turns a deliberate safety rail into an
incident.

`metaproject new` still prompts for title, description, and author unless you supply
them or pass `--yes`. Give it what it needs and it runs unattended.

Read-only or safe to run whenever they would help — none of these write anything except
`backfill`, and `backfill` only ever *creates* a file that did not exist: `review`,
`universe`, `learn list`, `learn show`, `backfill` (and any `--dry-run`).

## Scaffolding a new project

```bash
metaproject new rover-api \
  --title "Rover Telemetry API" \
  --description "High-throughput telemetry streaming service" \
  --yes
```

This creates the directory, renders every scaffolded template into it (writing
`.metaproject.json` too), copies the project skills into `.agents/skills/`, and makes an
initial git commit. Add `--dry-run` first if you
want to show the user what will appear before anything is written. `--no-git` skips the
repository.

## Scaffolding into a directory that already has work in it

Pointing `new` at a directory that already contains files shows what is there and asks
for two separate confirmations — one to copy the templates in, one to set up git.
Existing files are kept as-is; only the missing template files are written.

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

## `metaproject backfill`: filling in missing documents yourself

Unlike `new .` on a populated directory, `backfill` needs no confirmation and is
permitted in agent sessions — it only ever *creates* files, never overwrites, and never
touches git. This is what a skill or hook uses to fill in a document `review` reports
missing, right when it is needed:

```bash
metaproject backfill                              # every missing deliverable and skill
metaproject backfill docs/SPEC.md docs/TECH-DESIGN.md   # exactly these, by name
metaproject backfill docs/HANDOFF.md              # on-demand deliverables must be named
```

With no file argument it creates every deliverable `new` would have scaffolded (skipping
on-demand ones) and copies any project skill whose `.agents/skills/<name>/` directory is
absent — an existing skill directory is never written into. Naming files touches only
those files, and also lets you create on-demand ones like `docs/HANDOFF.md`. Old names
still work: `backfill intent.md` or `backfill INTENT.md` creates `docs/INTENT.md`, and
`backfill design.md` creates `docs/TECH-DESIGN.md` — never a root-level file. An
existing named file is refused — nothing is written and the command exits non-zero — so
it never clobbers real content. `--dry-run` previews without writing.

## Auditing a project against the templates

```bash
metaproject review                       # this project
metaproject review /path/to/project
metaproject review --all --depth 2       # every project under the tree
```

Each project reports one of four states, and the distinction is worth keeping straight
when you summarize:

- `✓ CLEAN` — nothing missing, nothing drifted, no working document has lost a heading.
- `~ DRIFTED` — every file is present, but a governance file's content differs from its
  template, or a working document is missing a heading the template expects.
- `↻ OUTOFDATE` — nothing is missing, but a cycle document still sits at its old
  location (a root `intent.md`, a lowercase `docs/design.md`). It is not offered for
  Deploy — that would create a blank copy beside the real one; `metaproject doctor`
  moves it. Wins over drift.
- `! INCOMPLETE` — a scaffolded deliverable is absent. Wins over everything else.

Drift in a governance file is not automatically a defect. A project that has grown a
genuinely better `AGENTS.md` is drifted *and correct*; that is the signal `learn` is
built to harvest. So report it as a finding, not a fault, and ask which direction the
user wants to move it before touching anything. Working-document structure drift is
different — it means the project is missing a section the cycle expects — and it is
never offered for Update; only `backfill`/`deploy` can add the missing document itself.

Remediation lives behind the interactive board (`u` update a drifted governance file, `d`
deploy a missing one). To apply a fix non-interactively, tell the user what `review`
found and let them run the board, write the file yourself from the template if that is
clearly what they want, or use `metaproject backfill` for a missing working document.

## Migrating an older project: `doctor`

Projects scaffolded before cycle documents moved into `docs/` keep them at the root under
lowercase names; `review` shows those projects as `↻ OUTOFDATE`. `metaproject doctor`
migrates, each fix behind the operator's confirmation: it moves the store's cycle
templates into `docs.template/` (one commit in the store), rewrites old paths in
`learn.targets`, moves each cataloged project's documents into `docs/` with their new
names (`git mv` when tracked; it never overwrites and never commits in the project),
installs missing project skills (a stale copy is reported, never overwritten), and
removes the old global `~/.claude/skills/metaproject/`. Only `metaproject doctor
--dry-run` runs in an agent session — run it to show the findings, then hand the
operator `metaproject doctor`.

## Promoting recurring drift into the templates

`learn` is the reflective half of the tool: it collects how projects have actually
diverged, clusters the divergences, scores them by how often and how recently they
recur, and proposes template edits for the operator to accept. For governance files this
still means body text and a model call; for working deliverables it means heading
structure only — `learn` never reads or proposes changes to their body text, and a
heading proposal (add or remove) needs corroboration from at least
`learn.min_structure_evidence` projects (default 2) locally, with no model involved.

```bash
metaproject learn list                  # pending proposals — safe, read-only
metaproject learn show 7                # rationale, proposed body, contributing projects
```

Two operations deserve real restraint:

- **`learn scan`** gathers evidence from every project and, for governance files, calls a
  model (`claude -p`) to synthesize proposals. It costs time and money, and it sends
  redacted diffs off the machine. The CLI refuses it in an agent session — surface the
  command it prints and let the user decide.
- **`learn apply <id>`** rewrites a template and commits it. That template governs every
  project scaffolded from here on. Nothing stops you mechanically, so the restraint has to
  come from you: read the proposal with `show`, tell the user what it would change and
  why, and let them accept it.

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

- **`docs/INTENT.md` / `docs/SPEC.md` / `docs/TECH-DESIGN.md` / `docs/PLAN.md`** — the
  cycle documents, one stage each, moving Draft → Approved as the operator signs off.
- **`docs/STATE.md`** — the live checklist: the 7-stage Process list, implementation phases,
  design invariants, verified facts, open items. Update it as tasks land, not at the end.
- **`docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`** — the
  long-lived record; `wrapup` appends each cycle's durable findings here and never resets
  them.
- **`docs/HANDOFF.md`** — written when work is interrupted, so the next session (or the next
  person) can resume without re-deriving context. On-demand: create it with `backfill`
  only when actually stopping mid-stream.
- **`AGENTS.md` / `CLAUDE.md`** — how to build, test, and work in this repo.

When you finish a meaningful chunk of work in one of these repos, updating `docs/STATE.md`
is part of finishing — not a separate chore to mention and skip.

See `references/documents.md` for what belongs in each file and how the 7-stage cycle
moves between them.

## Full command surface

`references/commands.md` has every command with its flags, plus copy-paste
non-interactive recipes. Read it when you need a flag this page does not cover.
