# Merge sdlc-skills into metaproject — research & design notes

**Date:** 2026-09-15 · **Status:** brainstorm complete, design approved in session, not yet an SDLC cycle
**Source:** planning session in worktree `merge-sdlc-skills` (branch `worktree-merge-sdlc-skills`)

## Problem

The SDLC cycle is split across two repos: metaproject owns the templates/CLI, the
sdlc-skills plugin repo owns the 7 cycle skills. They are coupled one-directionally by a
version-gated SessionStart hook (metaproject ≥ 0.7.0 + `.metaproject.json`), and
`ARCHITECTURE.md` records the split as an invariant ("the cycle lives in the sdlc-skills
plugin… which consumes these templates rather than carrying copies"). Two repos, two
version schemes, two doc sets for one product.

## Verified ground truth (2026-09-15)

**SDLC-skills repo** (`~/Projects/SDLC-skills`, local-only, **no git remote**, ~30 commits):

- 7 skills: `skills/{write-intent,generate-spec,generate-design,generate-plan,implement-plan,execute-tests,wrapup}/SKILL.md`
- `hooks/hooks.json` + `hooks/check-metaproject.sh` — SessionStart gate: metaproject ≥ 0.7.0
  on PATH (sort -V compare) and `.metaproject.json` at project root; always exits 0, notice only
- `.claude-plugin/plugin.json` (v0.0.2) + `.claude-plugin/marketplace.json`
- One shell test (`tests/test_check_metaproject.sh`), its own SDLC root docs, `.serena`
  memories, `.remember` history
- **Registered in Claude Code as a `directory` marketplace** pointing at the repo path
  (`~/.claude/plugins/known_marketplaces.json` → `source: directory,
  path: /Users/johnfricker/Projects/SDLC-skills`) — sessions' live `sdlc-skills:*`
  skills are served from that path. Moving/deleting the repo breaks the installed plugin
  until unregistered.

**Metaproject side:**

- Already ships one Claude skill (`src/metaproject/skill/`, SKILL.md + references) that
  `skills.py::install_skill` installs to `~/.claude/skills/metaproject/` during `init`,
  with per-skill semantics: CURRENT (skip) / INSTALLED / UPDATED / STALE (refuse without
  `--force`; never silently clobber operator edits). Generalizes cleanly to N skills.
- Wheel package-data currently `templates/**` + `skill/**` (hatchling).
- `bump_version.sh` heuristics: new files → minor/major bump under major-0 policy.

## Decisions (locked in session)

| Question | Decision |
|---|---|
| Outcome | Full absorption: single source of truth, `init` as distribution channel, fewer repos, co-versioning — all four |
| Claude Code surface | **init-installed skills** (no plugin, no marketplace) |
| Git history | **Preserve** via `git subtree add` |
| Skill names | **Bare names** (`~/.claude/skills/write-intent/` etc.); collision risk accepted |
| Session gate | **In-skill check only** — precondition preamble in each SKILL.md; no SessionStart hook |

## Approaches considered

- **A — staging subtree, curate immediately (CHOSEN):** `git subtree add --prefix=sdlc-skills-import`,
  then `git mv` the 7 SKILL.md files into `src/metaproject/skills/`, extend `skills.py`,
  delete the staging prefix and all plugin/hook/marketplace files. Clean final layout,
  history in log; gives up clean future `subtree pull` (acceptable — source repo retires).
- **B — permanent vendored subtree:** keep `sdlc-skills/` intact at repo root. Future pulls
  work, but permanently imports the foreign repo's root docs/`.serena`/`.remember noise and
  complicates wheel excludes. Rejected.
- **C — fresh import:** cleanest log, zero blame across boundary. Rejected (history preservation chosen).

## Approved design

### 1. History import

```
git remote add sdlc-skills /Users/johnfricker/Projects/SDLC-skills
git fetch sdlc-skills
git subtree add --prefix=sdlc-skills-import sdlc-skills main
```

Then curate: `git mv sdlc-skills-import/skills/<stage>/SKILL.md → src/metaproject/skills/<stage>/SKILL.md`
for the 7 stages; delete the staging prefix (plugin.json, marketplace.json, hooks/, the repo's
own SDLC docs, its shell test).

### 2. Layout, wheel, `skills.py`

- New `src/metaproject/skills/` (plural) with the 7 SKILL.md; existing `src/metaproject/skill/`
  (metaproject's own skill) untouched.
- `pyproject.toml` package-data gains `"skills/**"`.
- `skills.py`: refactor `install_skill` to take an explicit source dir; add
  `install_all_skills()` installing the metaproject skill + the 7, returning per-skill
  states (same CURRENT/INSTALLED/UPDATED/STALE + force semantics). `init` calls it and
  lists each skill's state.

### 3. SKILL.md content edits (during curation)

- Standard precondition preamble in each of the 7, replacing the SessionStart hook:
  *requires a metaproject-managed project (`.metaproject.json` at root) and `metaproject`
  on PATH; if absent, stop and tell the operator to run `metaproject new .`*. Version
  check dropped — skills and CLI ship in one wheel.
- Strip plugin-namespace references: `/sdlc-skills:write-intent` → `/write-intent`,
  "this plugin" → "these skills", stage cross-references updated.

### 4. Tests

New `tests/test_sdlc_skills.py`:
- (a) all 7 SKILL.md bundled as package data
- (b) each has valid frontmatter (name + description) and contains the managed-project precondition
- (c) no stale `sdlc-skills:` namespace strings remain
- (d) `install_all_skills` installs all 8 into a tmp target dir; second run → CURRENT, no writes

Existing ~588 tests untouched. Gate: `make format && make lint && make test`.

### 5. Migration sequence (operator, ordered)

1. Merge cycle to main; `make bump-version` (heuristics read new files → minor → **0.8.0**);
   `uv tool install --force .`
2. Claude Code: uninstall sdlc-skills plugin + remove its directory marketplace (`/plugin`)
3. `metaproject init --force` → installs/refreshes all 8 skills into `~/.claude/skills/`
4. Archive `~/Projects/SDLC-skills`: final commit adding a README pointer
   ("absorbed into metaproject ≥ 0.8.0"), leave on disk read-only; `.serena`/`.remember` stay there

### 6. Docs

- `ARCHITECTURE.md`: flip the "cycle lives in the sdlc-skills plugin" invariant to "cycle
  skills ship in the metaproject wheel and are installed by `init`"; add cycle-index row.
- `README.md`: replace plugin-dependency story with init-install story (bare names, in-skill gate).
- DESIGN-INVARIANTS / VERIFIED-FACTS entries at wrapup.

## Side effects & risks

1. **Live plugin breakage:** sessions' `sdlc-skills:*` skills come from the directory
   marketplace at the repo path. Uninstall plugin + remove marketplace **before** archiving
   the repo; order matters.
2. **Namespace loss:** `/sdlc-skills:write-intent` → `/write-intent`. Bare user-level names
   can collide with future plugins — accepted.
3. **Gate loss:** no proactive SessionStart banner; un-managed projects discover the
   precondition only when a skill runs. Version-gate drift becomes impossible (co-versioned wheel).
4. **Documented invariant flips:** `ARCHITECTURE.md` + `template-source-of-truth` cycle docs
   need updating.
5. **Release coupling:** skill changes now force a metaproject release (semver rides the wheel).
6. **Stranded artifacts:** old repo's serena memories, `.remember` history, cycle archives
   stay behind in the archived repo.
7. **Blame note:** §3 content edits land blame in the curation commit, not the original —
   limited to preamble/namespace lines.
8. **Mechanics:** subtree-add uses a local-path remote (no network); `.DS_Store` files are
   untracked in SDLC-skills so they don't come across; sandboxed test runs need
   `--basetemp` under `/private/tmp` (known quirk).

## Open next steps

- [ ] Run `/write-intent` on this note to open the SDLC cycle in metaproject (intent.md)
- [ ] Worktree `merge-sdlc-skills` (branch `worktree-merge-sdlc-skills`) exists, unused so far — reuse or remove
- [ ] Note: main checkout has a separate in-flight `metaproject doctor` cycle (intent/spec
      drafted, uncommitted, 2026-09-15 15:04) — sequence the two cycles, don't interleave
