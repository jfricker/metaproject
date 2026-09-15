# MetaProject — State

## Process
- [x] 1. Review intent.md and create spec.md
- [x] 2. Create plan.md from spec.md
- [x] 3. Implementation and verification

## Implementation phases

- [x] 1. `skills.py`: `install_skill(prune_extra=...)` + tests (commit fcd4fa6)
- [x] 2. `doctor.py`: CheckResult + four checks/fixes, reusing owning modules
- [x] 3. `cli.py`: `doctor` command with `--dry-run`, agent-session guard, exit codes
- [x] 4. `tests/test_doctor.py`: acceptance criteria 1–7 (15 new tests)
- [x] 5. README "Upgrading" section
- [x] 6. Full gate via make: ruff clean, 603 passed (`--basetemp=/private/tmp/mp-gate-doctor2`,
      worktree path trips the claude-arg guard otherwise), wheel builds with doctor.py
      shipped; all 7 acceptance criteria covered by tests or the gate.

## Design invariants (regression guards)

## Open items carried into plan.md

## Verified facts (do not re-investigate)
