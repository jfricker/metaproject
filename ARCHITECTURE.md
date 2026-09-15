# MetaProject — Architecture

Long-lived index. Unlike `intent.md`/`spec.md`/`design.md`/`plan.md`/`STATE.md`, this
file is never reset — `wrapup` appends to it at the end of every cycle. It is the sum of
every cycle's specifications plus the decisions made along the way, not a from-scratch
description of the system.

## Executive overview

`metaproject` is a Python CLI (Typer + Rich, Python 3.11+, built with uv/hatchling) that
owns SDLC governance documents across a workspace of projects. It scaffolds new projects
(`new`, with confirmed backfill into existing directories), audits drift between
projects and their templates (`review`, with a compliance-board TUI), catalogs the
workspace (`universe`), and harvests recurring drift back into the templates
(`learn` — evidence collection, a `claude -p` synthesis stage, a ranked proposal ledger
in `universe.db`, and an operator-reviewed apply path that commits each acceptance to
the git-backed template store).

The template store is now **bundled with the package** (`src/metaproject/templates/`)
and seeded to `~/.metaproject/templates/` by `init` — metaproject is the single source
of truth for SDLC document templates. Deliverables are declared in one module
(`deliverables.py`: GOVERNANCE, WORKING, ON_DEMAND classes), so scaffold, review, and
learn all classify documents identically; `identity.py` writes a per-project
`.metaproject.json` that anchors variable resolution across rescans. Documents are
compared structurally where structure is the meaning (`markdown.py` heading trees back
`review`'s structure drift and `learn`'s local heading proposals — which never reach
the model egress path), and textually where text is the meaning. The 7-stage SDLC cycle
itself lives in the `sdlc-skills` plugin (`~/Projects/SDLC-skills`), which consumes
these templates rather than carrying copies.

## Cycle index

| Date | Slug | Summary | Archive |
|---|---|---|---|
| 2026-09-04 | improve-learn-command | Rebuilt `learn` as a corroborated proposal pipeline (render-and-diff evidence, `claude -p` synthesis, ranked ledger, rich acceptance TUI). *(row added retroactively at 2026-09-15 wrapup — predates this index)* | [docs/archive/2026-09-04-improve-learn-command/](docs/archive/2026-09-04-improve-learn-command/) |
| 2026-09-15 | template-source-of-truth | Made metaproject the source of truth for SDLC templates: deliverable classes, `.metaproject.json` identity, structural drift/learning, bundled template store replacing root `templates/`, confirmed backfill (`new .`, `metaproject backfill`), agent-session guards, and the sdlc-skills repo's SDLC surface. Spec: [spec.md](docs/archive/2026-09-15-template-source-of-truth/spec.md), design: [design.md](docs/archive/2026-09-15-template-source-of-truth/design.md). | [docs/archive/2026-09-15-template-source-of-truth/](docs/archive/2026-09-15-template-source-of-truth/) |
