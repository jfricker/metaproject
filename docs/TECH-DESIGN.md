# Absorb sdlc-skills into metaproject; move cycle docs to docs/ — Design

**Author**: John Fricker.
**Derived from**: spec.md (2026-09-28).
**Last updated**: 2026-09-28.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-28).

Requirement IDs refer to spec.md. This file becomes `docs/TECH-DESIGN.md` when the
implementation's first step moves this repo's documents (R-SELF-1, FC-2).

## Affected components

### 1. `deliverables.py`: one declaration for names, paths and aliases (R-DOC-0/1/4)

The deliverable table keeps its four classes; only paths change:

| Class | Paths |
|---|---|
| governance | `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore` (unchanged) |
| working | `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md` |
| on-demand | `docs/HANDOFF.md` |
| directory | `docs`, `docs/archive` (unchanged) |

Additions, all in this module so nothing re-derives the mapping:

- `LEGACY_NAMES: Mapping[str, str]` — old root name → new path: `intent.md` →
  `docs/INTENT.md`, `spec.md` → `docs/SPEC.md`, `design.md` → `docs/TECH-DESIGN.md`,
  `plan.md` → `docs/PLAN.md`, `STATE.md` → `docs/STATE.md`, `HANDOFF.md` →
  `docs/HANDOFF.md`, `ARCHITECTURE.md` → `docs/ARCHITECTURE.md`.
- `canonical_path(name) -> Optional[str]` — the alias rule behind R-DOC-4. Matches, case-
  insensitively, a declared path (`docs/INTENT.md`), its basename (`INTENT.md`), or a
  legacy name (`intent.md`, `design.md`); returns the declared path. Anything else is
  returned unchanged so `backfill` still accepts arbitrary template-backed paths.
- `legacy_locations(project_dir) -> Dict[str, str]` — declared path → the legacy
  file actually present. It lists directory entries (`os.listdir`) and compares names
  exactly, so on APFS `docs/INTENT.md` is never "found" because `intent.md` exists
  (R-NFR-6). A relocated document counts as legacy when it is absent at its exact new
  path and present either at the root (old or new name) or in `docs/` under its old
  name.
- `exact_exists(path) -> bool` — the same exact-name check, used wherever a relocated
  deliverable's presence is decided.

### 2. Template store layout (R-DOC-2)

The bundled store (`src/metaproject/templates/`) moves the seven templates with
`git mv` into `docs.template/`, renamed: `INTENT.template.md`, `SPEC.template.md`,
`TECH-DESIGN.template.md`, `PLAN.template.md`, `STATE.template.md`,
`HANDOFF.template.md`, `ARCHITECTURE.template.md`. `transform_template_name` and
`resolve_template_entry` already map `docs.template/X.template.md` → `docs/X.md`, so
rendering, `review`, `learn` collect and `learn apply` need no path special-casing.
Template bodies that name cycle documents (`**Derived from**: intent.md`, the AGENTS and
CLAUDE templates' process sections, ARCHITECTURE's links) are edited to the new names.

One latent bug becomes live: `deploy_entry` renders a directory deliverable (`docs`) as
a whole tree without an `exclude`, so once `HANDOFF.template.md` lives under
`docs.template/`, deploying `docs` would create an on-demand document. `deploy_entry`
passes the on-demand paths (relative to the directory being rendered) as `exclude`, the
same set `scaffold_project` already passes at the root.

### 3. Project skills (R-IMP, R-SKL)

**Bundle.** SDLC skills live in `src/metaproject/sdlc_skills/<name>/SKILL.md`
(package data `sdlc_skills/**`); the metaproject skill stays in `src/metaproject/skill/`.

**`skills.py` is rewritten around project installs:**

- `BundledSkill(name, source_dir)` and `bundled_skills() -> Tuple[BundledSkill, ...]` —
  the single declaration (R-SKL-1): `metaproject` from `skill/`, plus every directory
  under `sdlc_skills/` whose `SKILL.md` exists, sorted by name.
- `project_skills_dir(project_dir) -> SkillsTarget` — returns the `.agents/skills`
  path, or a refusal reason when `.claude/skills` is a real directory or a symlink not
  resolving into the project's own `.agents/skills` (R-SKL-5).
- `skill_state(skill, dest) -> "missing" | "current" | "stale"` using the existing
  `is_skill_current` byte comparison (junk-filtered).
- `install_project_skills(project_dir, dry_run, tracker=None) -> SkillsReport` —
  create-only: writes a skill only when its destination directory is absent; reports
  `installed` / `current` / `stale` per skill (R-SKL-4). Created directories and files are
  recorded on the `TransactionalTracker` so a failed `new` rolls them back.
- Removed: `get_skill_install_dir`, `METAPROJECT_SKILL_DIR`, `install_skill`'s
  `force`/`prune_extra` paths, and `_prune_extra_files` (R-INI-2). Kept for doctor:
  `LEGACY_GLOBAL_SKILL_DIR = Path.home() / ".claude/skills/metaproject"`, computed at
  call time so tests can monkeypatch `HOME`.

**Callers.**

- `scaffold_project` calls `install_project_skills` right after `link_agent_skills` and
  before git initialisation, so the initial commit includes the skills (R-SKL-2,
  R-SKL-6). `new`'s result gains a `skills` report; `cli.new_cmd` prints it (dry-run:
  "Would install").
- `backfill_missing` in no-files mode runs the same call after deliverables; with named
  files it does not (R-SKL-3). `BackfillResult` gains `skills` and `skills_notice`.
- `review` and `learn` never call it. `learn.collect.iter_target_files` additionally
  drops any path under `.agents/` or `.claude/`, even if an operator lists it in
  `learn.targets` (R-SKL-8).

**Skill text.** Each SDLC SKILL.md gets one shared preamble (R-TXT-1), placed directly
under the title:

> **Precondition.** This project must be metaproject-managed: `.metaproject.json` at the
> repository root and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

The "Conventions (metaproject)" block loses its SessionStart bullet and version check;
the blank rule, document list, `backfill` examples and wrapup's archive/reset steps use
`docs/INTENT.md` etc. (R-TXT-3). Frontmatter `name` equals the directory name (R-SKL-7).

### 4. `review.py` (R-DOC-5)

`ReviewResult` gains `legacy: Dict[str, str]` (declared path → legacy location). In
`review_project`, a relocated working deliverable that is not `exact_exists` at its
declared path is looked up in `legacy_locations`; if found it goes to `legacy`, not
`missing_files` or `deployable`.

Verdicts gain a fourth state, `OUTOFDATE`: the project has every deliverable, but at
least one sits at its legacy location. `ReviewResult` adds the derived property
`is_current` (no `legacy` entries); `is_compliant` keeps meaning "nothing missing", and
`is_clean` now also requires `is_current`. The board's state function, in precedence
order:

| State | Glyph | Condition |
|---|---|---|
| `INCOMPLETE` (red) | `!` | something missing — unchanged, still wins |
| `OUTOFDATE` (cyan) | `↻` | nothing missing, `legacy` non-empty — migration comes before judging drift |
| `DRIFTED` (yellow) | `~` | current, but diffs or structure findings |
| `CLEAN` (green) | `✓` | none of the above |

Like the others it carries a glyph as well as a colour, so it survives `NO_COLOR` and a
pipe. The `Missing` column stays a count of missing files (legacy entries don't count).
The detail screen lists legacy entries under "Legacy location — run `metaproject
doctor`" with no action key, and `?` help documents the new state. `backfill_missing`
canonicalises named files through `canonical_path` before any existence check, and uses
`exact_exists` for relocated paths.

### 5. `learn/`, `universe.py`, `identity.py`, `config.py` (R-DOC-3, R-DOC-6)

- `DEFAULT_LEARN_TARGETS` already derives from `deliverables.learn_targets()`, so it
  follows the new paths. The existing `docs/` directory target overlaps; `iter_target_files`
  already de-duplicates.
- `learn apply` resolves the template through `resolve_template`, which now lands on
  `docs.template/…`; its target-section splice is unaffected. Existing ledger rows keyed
  by old names are left alone (FC-3).
- `universe.is_project_root` recognises `docs/INTENT.md` as well as root `intent.md`;
  `has_intent_md` / `has_state_md` / `has_handoff_md` are true for either location. The
  DB column names are unchanged (no schema migration).
- `identity.py` changes only a docstring.

### 6. `doctor.py` (R-DRX)

The check list and order after this cycle:

1. **Template-store layout** (new, R-DRX-1) — legacy root templates in the live store.
2. Template store — missing bundled templates (existing; runs after 1 so a migrated store
   isn't re-seeded).
3. **Config** — missing core targets (existing) plus legacy root paths in
   `learn.targets`, rewritten in place, order kept, de-duplicated (R-DRX-2).
4. **Orphaned global skill** (new, R-DRX-6) — `~/.claude/skills/metaproject/`; the fix
   removes that one directory (or unlinks it if it is a symlink).
5. Project identity (existing).
6. **Project docs** (new, R-DRX-3) — per cataloged, metaproject-managed project.
7. **Project skills** (new, R-DRX-4) — per cataloged, metaproject-managed project; the
   fix installs missing skills only. Stale skills and R-SKL-5 refusals are findings with
   no fix.

The global-skill check is deleted (R-DRX-5). Checks 6 and 7 confirm per project: they
call `_apply` once per project (name `project docs: <path>`), so declining one project
never blocks the next (R-DRX-7).

**Move primitive** — `doctor._relocate(root, src_rel, dest_rel, git_repo)`, shared by
checks 1 and 6:

1. Refuse if `dest_rel` `exact_exists` (report "conflict", leave both files).
2. `mkdir -p` the destination's parent.
3. If `git_repo` and the source is tracked (`git ls-files --error-unmatch`): `git mv`;
   otherwise `os.rename`.
4. If source and destination differ only in case (e.g. `docs/intent.md` →
   `docs/INTENT.md`), go through an intermediate name (`<dest>.metaproject-tmp`) in
   two steps (R-NFR-6).

Each move is independent, so a partial run can be re-run and completes the rest
(R-NFR-3). Project migrations never commit. The store migration commits only the moved
paths (`git commit -m "chore(templates): relocate cycle templates to docs.template/" --
<old> <new>`), so an unrelated dirty file in the store is neither committed nor a
blocker. New helpers in `git.py`: `is_tracked`, `git_mv`, `commit_paths`.

### 7. `cli.py` (R-INI)

`init` drops `report_skill_install`, the `--no-skill` option and the skill wording of
`--force`. `new` and `backfill` print the skills report and the R-SKL-5 notice. `doctor`'s
docstring and output list the new checks.

### 8. Import (R-IMP-1..4)

Run from this repo on a clean tree:

```
git remote add sdlc-skills /Users/johnfricker/Projects/SDLC-skills
git fetch sdlc-skills
git subtree add --prefix=sdlc-skills-import sdlc-skills main
git mv sdlc-skills-import/skills/<name> src/metaproject/sdlc_skills/<name>   # ×8
git rm -r sdlc-skills-import
git remote remove sdlc-skills
```

The subtree brings only committed history; SDLC-skills' pending `implement-plan` edit was
resolved before import (committed in part as `e6f42a4`, the rest dropped). Text edits
(preamble, paths, namespace) land in a separate commit after the move, so `git log
--follow` on each SKILL.md shows the move cleanly and blame for the edited lines is
confined to that commit.

### 9. Documentation and this repo (R-TXT, R-SELF, R-RET)

- `README.md`: replace the plugin story with project-local skills, bare names, the
  in-skill precondition, the new document layout, `doctor` migration, and the ordered
  retirement steps (R-RET-1).
- `AGENTS.md`, `CLAUDE.md` (Process section), `docs/ARCHITECTURE.md`: new paths and
  names; AGENTS.md's review-board description gains the `OUTOFDATE` state; the "cycle lives in the sdlc-skills plugin" invariant is replaced (R-TXT-4).
- The metaproject skill (`skill/SKILL.md`, `references/`): new paths; "each stage owned
  by an `sdlc-skills` skill" becomes "by a project skill copied in by `new`".
- This repo: `git mv` the cycle docs and `ARCHITECTURE.md` to `docs/` with the new names
  as the first implementation step, and run `metaproject backfill` (from the working
  tree) to populate `.agents/skills/`. Copy SDLC-skills'
  `docs/backlog/wrapup-delete-cycle-branch.md` into `docs/backlog/` (R-RET-2).

## Data flow / interfaces

```
new / backfill ──► deliverables (paths, aliases) ──► templates (docs.template/ tree) ──► project/docs/*.md
       │
       └────────► skills.bundled_skills() ──► install_project_skills ──► project/.agents/skills/<name>/
                                                     ▲                     (.claude/skills → symlink)
review ──► deliverables.legacy_locations ──► ReviewResult.legacy ──► board: "run doctor"
                                                     │
doctor ──► store layout ─► store ─► config ─► global skill ─► identity ─► project docs ─► project skills
             (_relocate + commit_paths)                              (_relocate, per project)  (install missing)
```

New or changed public interfaces:

| Interface | Change |
|---|---|
| `deliverables.LEGACY_NAMES`, `canonical_path`, `legacy_locations`, `exact_exists` | new |
| `skills.bundled_skills`, `project_skills_dir`, `skill_state`, `install_project_skills` | new |
| `skills.install_skill`, `get_skill_install_dir`, `METAPROJECT_SKILL_DIR` | removed |
| `ReviewResult.legacy`; `BackfillResult.skills`, `skills_notice` | new fields |
| `deploy_entry` | directory deploys exclude on-demand paths |
| `git.is_tracked`, `git_mv`, `commit_paths` | new |
| `metaproject init --no-skill` | removed |

## Alternatives considered

- **Ship skills inside the template store** (`~/.metaproject/templates/.agents.template/skills/…`)
  so `new`'s tree render copies them for free. Rejected: skills are package-owned and
  versioned with the wheel, not operator-editable templates; rendering would substitute
  Jinja variables inside skill text; `learn` and `doctor`'s missing-template check would
  treat them as templates.
- **Symlink project skills to one shared copy** (e.g. inside the installed package).
  Rejected: breaks when the venv moves or the wheel upgrades, and isn't committable
  (R-SKL-6).
- **Report legacy documents as missing.** Rejected by spec (R-DOC-5): it would invite
  Deploy, creating a blank `docs/INTENT.md` beside the real root `intent.md`.
- **A dedicated `metaproject migrate` command.** Rejected at intent: migration belongs to
  `doctor`, which already owns confirmed repairs.
- **`Path.exists()` for legacy detection.** Rejected: on APFS `docs/INTENT.md` and
  `docs/intent.md` are the same entry, so it cannot tell a migrated file from a legacy one.
- **Rewrite learn ledger keys.** Rejected by the owner (FC-3).

## Trade-offs and risks

- **Test churn.** Many tests hard-code root cycle-doc names and the global skill install.
  They are updated, not deleted (R-NFR-1); expect the largest share of the diff here.
- **Case-insensitive filesystem.** Every relocated-path presence check must use
  `exact_exists`; a missed one reads as "migrated" when it isn't. Tests run on APFS, so
  a fixture with lowercase `docs/intent.md` exercises it.
- **Sandbox.** This repo's `.agents/skills` is write-denied in the Claude Code sandbox;
  populating it (R-SELF-1) and any test writing a real `.agents/skills` outside tmp must
  run unsandboxed. Git-writing tests already need unsandboxed runs (VERIFIED-FACTS).
- **Mid-cycle switch.** After step 1 moves this repo's docs, the installed
  `sdlc-skills` plugin skills still read the root. Until the new wheel is installed and
  the project skills are in `.agents/skills/`, the remaining stages are run by following
  the bundled skill text, or with the plugin's paths mentally translated.
- **Skill updates don't propagate.** Projects keep the skill version they were
  scaffolded with; `doctor` only reports stale copies (FC-4). Picking up a new release's
  skills means deleting the directory and re-running `backfill`.
- **Bare-name collisions.** A future user-level skill named `write-intent` would shadow
  or be shadowed by the project copy. Accepted.
- **Retirement order.** Uninstall the plugin and remove its directory marketplace before
  archiving the SDLC-skills repo, or sessions lose their skills.

## Open questions

None.
