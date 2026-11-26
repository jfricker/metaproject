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
- [x] 4. Scaffold / backfill / adopt (39df8bd; 1215 passed)
- [x] 5. Doctor (e367e64; 1223 passed)
- [x] 6. CLI output and shim removal (7730506; 1238 passed)
- [x] 7. Docs, skill history (3ecf5c0; 1238 passed) — self-migration (`metaproject doctor .`) pending, operator-run

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to .metaproject/docs/DESIGN-INVARIANTS.md by wrapup -->
- Staging recovery never trusts repository content: a `.dest.txt` destination that is absolute, uses `..`, or resolves outside the home (symlinks included) is skipped (`tests/test_treeops.py`).
- `git.read_only_query` is the only git call reachable from agent-safe commands and refuses keys outside `READ_ONLY_KEYS` (`tests/test_git_read_only.py`).
- `bridges.py` never imports `skills`; it writes under `.claude/skills/<name>` only for manifest-recorded entries, and a foreign entry is changed only with `--force NAME` (`tests/test_bridges.py`).
- The source (`.agents/skills`) is installed whatever `.claude/skills` is; only "root with no home" refuses (R-SKL-5 retired) (`tests/test_skills_sync.py`).
- Manifest entry names are untrusted: unsafe names are dropped, writes/removals require the entry parent to be `.claude/skills`, and nothing is changed when `.claude` or `.claude/skills` resolves outside the project (c48165a, `tests/test_bridges.py`).
- `backfill` and `adopt` run only allowlisted read-only git queries (`tests/test_backfill.py`, `tests/test_adopt.py` allowlist tests).
- `doctor` checks run in order config, docs, skills legacy link, skills targets, project skills, skill shadowing, hook scripts; each is confirmed separately and agent sessions only report (`tests/test_doctor.py`).
- `skills status|sync` exit 1 only for unknown `--force`, newer manifest under update, I/O failure, no-home refusal; legacy link, foreign entries, write denied and shadowing exit 0 (`tests/test_skills_sync.py`, `tests/test_skills_sync_all.py`).
- A sync carries the manifest's `bridges` object through unchanged; v1 manifests are rewritten as v2 (`tests/test_skills_sync.py`).

## Open items carried into PLAN.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->
- Step 5 deviations: doctor `_apply` now turns a `MetaProjectError` from any fix into a "fix failed" finding (previously raised); the legacy-migration post-fix message prints through a local rich Console; identical unrecorded bridge entries are not doctor findings; a manifest write failure after a successful migration is not rolled back (the entries then read as identical foreign).
- Step 7: the bundled skill text may not contain the literal "SessionStart" (`tests/test_sdlc_skills.py`), so `references/commands.md` names "the web session bootstrap script (`scripts/metaproject-session.sh`)" instead.
- Recording `skills.targets` re-serialises the config as sorted, indented JSON (keys and values preserved, formatting not).

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to .metaproject/docs/VERIFIED-FACTS.md by wrapup -->
