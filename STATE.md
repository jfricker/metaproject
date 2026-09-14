# MetaProject — State

## Process
- [x] 1. write-intent: intent.md approved
- [x] 2. generate-spec: spec.md approved
- [x] 3. generate-design: design.md approved
- [x] 4. generate-plan: plan.md approved
- [ ] 5. implement-plan: plan steps implemented
- [ ] 6. execute-tests: verification green
- [ ] 7. wrapup: cycle archived

## Implementation phases
- [ ] A1. deliverables.py
- [ ] A2. markdown.py
- [ ] A3. identity.py + variable resolution
- [ ] A4. placeholder warnings + render exclusions
- [ ] B1. scaffold writes identity, skips on-demand
- [ ] B2. review classes
- [ ] B3. backfill_missing + `metaproject backfill`
- [ ] B4. TUI + CLI surfaces
- [ ] C1. structural evidence
- [ ] C2. learn/structure.py + api partition
- [ ] C3. apply heading proposals
- [ ] C4. drift signal for structure
- [ ] D1. templates
- [ ] D2. skill docs + README
- [ ] D3. discovery doc
- [ ] E1. sdlc-skills hook + Makefile
- [ ] E2. sdlc-skills skills
- [ ] E3. sdlc-skills repo docs + identity + version
- [ ] F. release on main (after merge)

## Design invariants (regression guards)
- Working deliverables are never updatable: `ReviewResult.updatable` reads only `diffs`,
  which holds governance files; structural drift lives in `structure` (design.md).
- Heading (structure) evidence never reaches the egress guard, confirmation, or any model
  prompt; it is turned into proposals locally (spec R-LRN-1, design.md).
- Heading proposals need ≥ `learn.min_structure_evidence` (default 2) projects; model
  proposals for governance files stay ranked, not gated (spec R-LRN-1c).
- A template missing from the live store is an error, never a silent fallback to the
  bundled copy (design.md).

## Open items carried into plan.md
- FC-3 (spec.md): live store refresh deferred to a future `metaproject doctor` command;
  operator refreshes `~/.metaproject/templates` by hand after merge (2026-09-14).
- `doctor` must also update a `config.json` that pins `learn.targets`, so new working
  deliverables get scanned (spec R-LRN-3, 2026-09-14).
- `doctor` must also refresh the installed skill at `~/.claude/skills/metaproject/`
  (spec R-DOC-1, 2026-09-14).

## Verified facts (do not re-investigate)
- The prior "improve learn command" cycle shipped (v0.6.0, 333 tests) but was never
  wrapped up; its docs, including its full STATE.md with invariants, facts and open
  items, are archived under `docs/archive/2026-09-04-improve-learn-command/` (2026-09-13).
