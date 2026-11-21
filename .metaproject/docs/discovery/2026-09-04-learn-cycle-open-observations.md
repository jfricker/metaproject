# Learn-cycle open observations

These are observations recorded by the "improve learn command" cycle (shipped v0.6.0)
that never went through a wrapup decision; saved here for later triage, not acted on.
Nothing has been re-verified against current code (2026-09-14).

## From: Open items carried into plan.md

- **[resolved in cycle]** ~~`README.md` §5 still documents the deleted line-diff harvester (`metaproject learn` as
  an append-to-template command).~~ **Resolved in Phase 7**: §5 was rewritten for the
  corroborated-proposal pipeline.
- Only the project-root `.gitignore` is parsed; nested per-directory ignore files and
  `.git/info/exclude` are not. Not needed by any acceptance case, and the hard denylist is
  the backstop. Revisit if a real workspace shows it matters.
- `score.py` groups evidence into candidates by normalized line, one line per candidate.
  That is the deterministic corroboration signal; it is not the proposal. Phase 3's `synth`
  is what turns a cluster (or several related clusters) into a coherent proposal body, and
  it may regroup. `group_candidates` exists so frequency/recency/activity can be measured
  and gated before any model runs.
- C13 ("project-specific text is not promoted") is listed in `expectations.json` as a
  Phase 2 case but is really Phase 3's: it constrains what the model may emit. `collect`
  already strips the placeholder class; the remaining absolute-path/project-name leak is a
  synthesis concern. Assert it in `tests/test_learn_synth.py`.
- C22's open question ("should Archived projects be scanned at all?") is answered
  *yes, at weight 0.1*: `collect` scans them and records the classification. The weighting
  itself is Phase 2's.
- C16 ("semantically identical, textually different") and C17 ("contradictory conventions
  are not merged") are model-judgment cases, and every Phase 3 test mocks the model. What
  is asserted is therefore what the pipeline *asks for*: the prompt requires reworded
  variants of one convention to be folded into a single proposal citing all of them, and
  forbids merging a contradiction into one recommendation (propose the corroborated
  majority; surface the minority separately). Whether the model obeys is measurable only
  against a live model, which no test may invoke. Recorded here rather than quietly
  claimed as passing.
- **The "missing `claude` exits non-zero" gate is asserted at the exception boundary**, not
  at the process boundary: `synthesize` raises `ModelUnavailableError` naming the binary,
  having assembled no prompt (asserted by patching `build_prompt`) and left the template
  store byte-identical. Turning that into an exit code is Phase 4's, since `cli.py` is out
  of Phase 3's scope; the existing `learn` stub's exit 1 would have made a CLI-level
  assertion vacuous.
- `is_generalizable` rejects a proposal that mentions a **contributing project's** name,
  case-insensitively at word boundaries. Deliberately blunt: a genuinely general proposal
  has no reason to name a project that fed it. The known false-positive class is a project
  whose name is an ordinary word (the fixture has `echo`, `forge`, `spire`), which could
  cost a legitimate proposal. Scoping the check to the bundle's own contributors keeps the
  blast radius small; revisit only if a real workspace shows it biting.
- `evidence_hash` identity is stable against model rewording but **not** against the
  evidence set growing: a twelfth project stating the convention in genuinely new words
  adds a `source_line` and therefore mints a new identity, which a prior rejection does not
  suppress. This is the accepted direction of failure — new content arguably *is* a new
  candidate, whereas a reworded body over identical evidence is not. The alternative
  (hashing the body) fails in the far worse direction, every single scan.
- `run_claude` has no test of its own beyond `claude_command`: exercising it would mean
  spawning a subprocess, which the Phase 3 gate forbids. The autouse `no_model_ever`
  fixture in `tests/test_learn_synth.py` patches both `subprocess.run` (for any argv
  mentioning `claude`) and `synth.run_claude`, so the "no test invokes a model" gate is
  enforced by the suite rather than trusted.

## From: Closing — what shipped, and what is still open

`src/metaproject/learn.py`'s line-diff harvester is gone. In its place,
`src/metaproject/learn/` is a nine-module corroborated-proposal pipeline —
`collect`, `guard`, `score`, `store`, `synth`, `apply`, `drift`, `api`, `tui` — reached
through a `learn` command group with a hidden default command, backed by three new tables
in `universe.db` and a git-backed template store. 333 tests, `make lint` clean, version
0.6.0. Every plan.md §2 phase gate was met; each phase's headline gates were
mutation-checked rather than trusted.

The following were deferred or narrowed by earlier phases and remain open. None is a
regression; each is a bounded, deliberate limit that a future change would have to lift.

**Model judgment is asserted as intent, not as behavior (Phase 3).**
- **C16** ("semantically identical, textually different" variants fold into one proposal)
  and **C17** ("contradictory conventions are not merged") are properties of what the
  model does, and no test may invoke a model. What is asserted is what the prompt *asks
  for*. Whether the model obeys is measurable only against a live model. Unverified, and
  recorded as unverified.
- `run_claude` itself has no test beyond `claude_command`, for the same reason: exercising
  it means spawning a subprocess, which the Phase 3 gate forbids.

**TUI (Phase 5).**
- `read_key`'s terminal branch (`termios`/`tty` raw-mode read) is `# pragma: no cover` and
  is exercised by no test — testing it needs a real PTY. Everything above it is tested
  through the `read_key` seam, so a break here would surface only in manual use.
- **There is no paging for a long proposal.** `render_candidate` paints the whole diff in
  one repaint; a proposal taller than the terminal scrolls off the top and cannot be
  scrolled back within the TUI. `learn show <id>` is the workaround. spec.md §5.4.5 does
  not require paging, so this is a usability gap, not a gate miss.

**Drift signal (Phase 6).**
- The `review` drift signal is **not surfaced anywhere in the UI.** It multiplies a
  contributing project's weight inside `score`, but nothing in `learn list`, `learn show`,
  or the TUI's provenance view tells the operator that a score was boosted or which
  projects `review` corroborated. `DriftSignal.reports()` exists to explain it; no caller
  uses it. An operator therefore cannot account for the number they are being ranked by.
- `DriftSignal.missing` is recorded and deliberately never scored — a missing file has no
  added lines, so there is nothing for a proposal to be about. Wiring it into scoring would
  invent evidence. Intentional; noted so it is not "fixed" later.
- **`review.py`'s narrowness bounds the signal's value.** `review_project` diffs exactly
  one deliverable, `AGENTS.md`, and diffs it against the *unrendered* template. So the
  boost is near-uniform across `AGENTS.md` and absent everywhere else. That is a property
  of `review`, not of `drift.py`: widening `review` to diff more deliverables (and to
  render before diffing, as `collect` does) would sharpen the signal with no change in
  `learn`.

**CLI surface (Phase 4).**
- `--templates` is accepted on `list`, `show` and `reject` but never read — those three
  are read-only against the ledger and never touch the template store. spec.md §5.4.4
  mandates the flag on all subcommands, so it is kept for a uniform surface; it is inert
  on those three, and passing it changes nothing.

**Collection and scoring limits (Phases 1–2).**
- Only the project-root `.gitignore` is parsed. Nested per-directory ignore files and
  `.git/info/exclude` are not. The hard denylist is the backstop.
- `is_generalizable` rejects a proposal naming a *contributing* project, case-insensitively
  at word boundaries. The known false-positive class is a project whose name is an ordinary
  word (`echo`, `forge`, `spire` in the fixture), which could cost a legitimate proposal.
- `evidence_hash` identity is stable against model rewording but **not** against the
  evidence set growing: a new project stating the convention in genuinely new words mints a
  new identity, which a prior rejection does not suppress. Accepted direction of failure —
  the alternative (hashing the body) fails far worse, every scan.
- `evidence_score` is a plain sum of weights, so ~10 `Archived` projects carry about as
  much weight as one `Active Now` project. Deliberate: the number stays explainable by the
  provenance list.
- `score.group_candidates` clusters one candidate per normalized line. That is the
  corroboration signal, not the proposal; `synth` regroups. Fine today, but it means
  corroboration is measured line-wise even when a convention spans several lines.

**Not in scope, and still not.**
- `learn` proposes additions and modifications only. Proposing a *removal* from a template
  is out of scope per spec.md §5.4.6 and nothing implements it.
- `learn.targets` is configurable but the shipped default list is what every test and
  fixture exercises; other target sets are untried.

---

Source: [archived STATE.md](../archive/2026-09-04-improve-learn-command/STATE.md)
