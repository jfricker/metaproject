# MetaProject — State

## Process

<!-- each stage ticks its own item here as it completes -->
- [x] 1. write-intent: INTENT.md approved
- [x] 2. generate-spec: SPEC.md approved
- [x] 3. generate-design: TECH-DESIGN.md approved
- [x] 4. generate-plan: PLAN.md approved
- [ ] 5. implement-plan: code and tests written
- [ ] 6. execute-tests: tests passing
- [ ] 7. wrapup: cycle archived

## Implementation phases

<!-- written by implement-plan as steps land -->
- [x] 1. Foundations: `treeops.py`, manifest v2, `identity.update_settings`, `git.read_only_query` (10a4a5e, 77bdbfe; 1142 passed)
- [x] 2. `bridges.py` in isolation (1cca5fe; 1187 passed)
- [x] 3. Wire bridges into skills (827929f; 1201 passed)
- [ ] 4. Scaffold / backfill / adopt
- [ ] 5. Doctor
- [ ] 6. CLI output and shim removal
- [ ] 7. Docs, skill history, self-migration

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to .metaproject/docs/DESIGN-INVARIANTS.md by wrapup -->
- Staging recovery never trusts repository content: a `.dest.txt` destination that is absolute, uses `..`, or resolves outside the home (symlinks included) is skipped (`tests/test_treeops.py`).
- `git.read_only_query` is the only git call reachable from agent-safe commands and refuses keys outside `READ_ONLY_KEYS` (`tests/test_git_read_only.py`).
- `bridges.py` never imports `skills`; it writes under `.claude/skills/<name>` only for manifest-recorded entries, and a foreign entry is changed only with `--force NAME` (`tests/test_bridges.py`).
- The source (`.agents/skills`) is installed whatever `.claude/skills` is; only "root with no home" refuses (R-SKL-5 retired) (`tests/test_skills_sync.py`).
- Manifest entry names are untrusted: unsafe names are dropped, writes/removals require the entry parent to be `.claude/skills`, and nothing is changed when `.claude` or `.claude/skills` resolves outside the project (c48165a, `tests/test_bridges.py`).
- A sync carries the manifest's `bridges` object through unchanged; v1 manifests are rewritten as v2 (`tests/test_skills_sync.py`).

## Open items carried into PLAN.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to .metaproject/docs/VERIFIED-FACTS.md by wrapup -->
