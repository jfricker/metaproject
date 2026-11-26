# MetaProject — Architecture

Long-lived index. Unlike `INTENT.md`/`SPEC.md`/`TECH-DESIGN.md`/`PLAN.md`/`STATE.md`, this
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
`.metaproject/config.json` (formerly root `.metaproject.json`, still read as a fallback) that anchors variable resolution across rescans; the user's own settings live in `~/.metaproject/settings.json`. Documents are
compared structurally where structure is the meaning (`markdown.py` heading trees back
`review`'s structure drift and `learn`'s local heading proposals — which never reach
the model egress path), and textually where text is the meaning. The 7-stage SDLC cycle
skills ship in the metaproject wheel (`src/metaproject/sdlc_skills/`) and are copied
into each project's `.agents/skills/` by `new`/`backfill`/`adopt` (the one source, read natively by Copilot, Codex, Antigravity, ZCode, Gemini CLI and Cursor), and `bridges.py` exposes them to Claude Code through manifest-tracked per-skill entries in `.claude/skills/<name>` (relative symlinks, or copies on Windows / `core.symlinks=false`), never a directory symlink; cycle documents live in each
project's `.metaproject/docs/` (leaving `docs/` free for the project's own documentation), and `doctor` migrates older root and `docs/` layouts.

## Cycle index

| Date | Slug | Summary | Archive |
|---|---|---|---|
| 2026-09-04 | improve-learn-command | Rebuilt `learn` as a corroborated proposal pipeline (render-and-diff evidence, `claude -p` synthesis, ranked ledger, rich acceptance TUI). *(row added retroactively at 2026-09-15 wrapup — predates this index)* | [docs/archive/2026-09-04-improve-learn-command/](archive/2026-09-04-improve-learn-command/) |
| 2026-09-15 | template-source-of-truth | Made metaproject the source of truth for SDLC templates: deliverable classes, `.metaproject.json` identity, structural drift/learning, bundled template store replacing root `templates/`, confirmed backfill (`new .`, `metaproject backfill`), agent-session guards, and the sdlc-skills repo's SDLC surface. Spec: [spec.md](archive/2026-09-15-template-source-of-truth/spec.md), design: [design.md](archive/2026-09-15-template-source-of-truth/design.md). | [docs/archive/2026-09-15-template-source-of-truth/](archive/2026-09-15-template-source-of-truth/) |
| 2026-09-15 | metaproject-doctor | Added `metaproject doctor [--dry-run]`: four environment checks (template store, `learn.targets`, global skill, project identity anchors) with per-check confirmed fixes routed through the owning modules; `install_skill` gained opt-in `prune_extra`. Universe check deferred. Spec: [spec.md](archive/2026-09-15-metaproject-doctor/spec.md), design: [design.md](archive/2026-09-15-metaproject-doctor/design.md). | [docs/archive/2026-09-15-metaproject-doctor/](archive/2026-09-15-metaproject-doctor/) |
| 2026-09-16 | universe-hard-scoping-and-details-tui | Hard-scoped `universe` to the configured `project_home` (`resolve_scan_root` refuses outside roots, symlinks included, exit 1 before the DB opens) and made a read-only Textual browser the default no-args view: list → project detail → worktree detail with live bounded git inspection (`gitinfo.py`, staleness verdict + separate uncommitted flag) behind the shared `tui_enabled` gate; `textual==8.2.8` pinned. Spec: [spec.md](archive/2026-09-16-universe-hard-scoping-and-details-tui/spec.md), design: [design.md](archive/2026-09-16-universe-hard-scoping-and-details-tui/design.md). | [docs/archive/2026-09-16-universe-hard-scoping-and-details-tui/](archive/2026-09-16-universe-hard-scoping-and-details-tui/) |
| 2026-09-29 | absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs | Absorbed the 8 SDLC cycle skills and metaproject skill into the package and project-local `.agents/skills/` (`new`/`backfill`), relocated cycle documents to `docs/` (`INTENT.md`, `SPEC.md`, `TECH-DESIGN.md`, `PLAN.md`, `STATE.md`, `HANDOFF.md`, `ARCHITECTURE.md`), added `doctor` migrations for store layout, project docs, and project skills, and added `OUTOFDATE` compliance detection for legacy doc locations. Spec: [SPEC.md](archive/2026-09-29-absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs/SPEC.md), design: [TECH-DESIGN.md](archive/2026-09-29-absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs/TECH-DESIGN.md). | [docs/archive/2026-09-29-absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs/](archive/2026-09-29-absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs/) |
| 2026-11-21 | move-docs-to-metaproject-docs | Relocated all metaproject-owned documents and directories into `.metaproject/docs/` (leaving `docs/` to the project), moved the bundled template store to `.metaproject.template/docs.template/`, added no-args `backfill` legacy skips (`R-LOC-5`), updated `universe`/`learn` to support all three layouts while skipping nested `.metaproject/docs/archive/` projects, extended `doctor` to migrate store layouts/configs/projects/subdirs (`git mv`/`git rm` + empty/junk-only `docs/` cleanup), updated all 12 bundled skills with `--hidden` search guidance + `skill_history.json`, and self-migrated this repository. Spec: [SPEC.md](archive/2026-11-21-move-docs-to-metaproject-docs/SPEC.md), design: [TECH-DESIGN.md](archive/2026-11-21-move-docs-to-metaproject-docs/TECH-DESIGN.md). | [.metaproject/docs/archive/2026-11-21-move-docs-to-metaproject-docs/](archive/2026-11-21-move-docs-to-metaproject-docs/) |
| 2026-11-21 | move-project-identity-to-metaproject-config | Moved the project config from root `.metaproject.json` to `.metaproject/config.json` behind one resolver (`identity.config_path`/`has_config`, legacy fallback, user-store dir never an anchor) and renamed the user config to `~/.metaproject/settings.json`; `doctor` gained config-file-name, project-config (move / remove identical / report differing) and hook-script-refresh checks, `review` reports a legacy `.metaproject.json` as `OUTOFDATE`, hook scripts read both paths, docs and skills updated, repository self-migrated. Spec: [SPEC.md](archive/2026-11-21-move-project-identity-to-metaproject-config/SPEC.md), design: [TECH-DESIGN.md](archive/2026-11-21-move-project-identity-to-metaproject-config/TECH-DESIGN.md). | [.metaproject/docs/archive/2026-11-21-move-project-identity-to-metaproject-config/](archive/2026-11-21-move-project-identity-to-metaproject-config/) |
| 2026-11-26 | harness-neutral-project-skills | Replaced the whole-directory `.claude/skills → .agents/skills` symlink with per-skill Claude Code bridge entries (`bridges.py`; symlink or copy, `skills.targets`/`skills.link_mode`, manifest v2 ownership, foreign entries untouched unless `--force`), retired the R-SKL-5 refusal, added `treeops.py` (atomic swap, staging recovery confined to the home), restated the git rule to allowlisted read-only `git config --get` queries, added doctor checks for the legacy link (migration naming user skills that would be lost), `skills.targets` and shadowing, and new `skills status` bridge output/JSON/exit codes. Spec: [SPEC.md](archive/2026-11-26-harness-neutral-project-skills/SPEC.md), design: [TECH-DESIGN.md](archive/2026-11-26-harness-neutral-project-skills/TECH-DESIGN.md). | [.metaproject/docs/archive/2026-11-26-harness-neutral-project-skills/](archive/2026-11-26-harness-neutral-project-skills/) |
