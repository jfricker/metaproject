# Per-file confirm in `learn scan`

**Status**: draft, not yet implemented.

## Context

`learn scan` currently gates egress once: `guard_evidence()` collects and redacts
evidence for every target file across every project, `confirm_send()` shows one
manifest for the whole run, and a single y/N either sends everything or aborts
everything (`api.py::scan`, `guard.py::confirm_send`). Synthesis then loops bundles
(`synth.bundle_evidence` groups evidence one bundle per target file, `synth.synthesize`
calls `claude -p` once per bundle) with no further operator input.

The operator wants that collapsed into one confirmation per target file: before each
file's evidence goes to the model, they see that file's slice of the manifest and
choose send or skip, file by file, rather than one all-or-nothing gate up front.

## Approach

Keep the mechanism/policy split the codebase already has: `synth.py` stays a pure
mechanism (given evidence, call the model) with no I/O; `guard.py` stays the home for
manifest rendering and the `input()`-based confirmation prompts; `api.py` wires them
together. Concretely:

### 1. `src/metaproject/learn/synth.py`

- `synthesize()` gains one new optional parameter:
  `confirm_fn: Optional[Callable[[Bundle], bool]] = None`.
- Inside the existing `for bundle in bundle_evidence(records):` loop, before chunking
  and calling the model, ask: `if confirm_fn is not None and not confirm_fn(bundle):`
  → append `bundle.target_file` to a new `declined` list and `continue` (skip this
  bundle entirely — no chunks, no `claude -p` calls, no entry in `calls_by_target`).
- `SynthResult` gains `declined: Tuple[str, ...] = ()`.
- Default (`confirm_fn=None`) preserves today's behavior exactly — every existing
  `synthesize(...)` call in the test suite that doesn't pass `confirm_fn` is
  unaffected.

### 2. `src/metaproject/learn/guard.py`

- Factor `confirm_send`'s ask-once logic into a small shared helper, then add a
  per-file counterpart that reuses it:

  ```python
  def _ask_to_send(prompt_text, assume_yes, confirm_fn) -> bool:
      if assume_yes:
          return True
      ask = confirm_fn or _default_confirm
      return bool(ask(prompt_text))

  def confirm_send(manifest, assume_yes=False, confirm_fn=None) -> bool:
      return _ask_to_send(f"{manifest.render()}\nSend this to the model?", assume_yes, confirm_fn)

  def confirm_file_send(target_file, manifest, assume_yes=False, confirm_fn=None) -> bool:
      return _ask_to_send(f"{manifest.render()}\nSend `{target_file}` to the model?", assume_yes, confirm_fn)
  ```

  `confirm_send` keeps its exact current signature/behavior/tests. `confirm_file_send`
  is new, built from `build_manifest(bundle_records, [])` (already public) so the
  operator sees the same per-project/size/kind lines as today, scoped to one file.

### 3. `src/metaproject/learn/api.py::scan`

- Drop the single upfront `confirm_send(guarded.manifest, ...)` gate and the
  early-return-on-decline branch.
- If `guarded.excluded` is non-empty, print it once, informationally, before any
  per-file prompt (`print(build_manifest([], guarded.excluded).render())`) — exclusion
  is structural (gitignore/denylist/binary), never a per-file choice, so it's a notice,
  not a question.
- Build a closure and pass it through:

  ```python
  def confirm_bundle(bundle: Bundle) -> bool:
      manifest = build_manifest(list(bundle.records), [])
      return confirm_file_send(bundle.target_file, manifest, assume_yes=yes, confirm_fn=confirm_fn)

  result = synthesize(guarded.records, config=config, model=model, runner=runner, confirm_fn=confirm_bundle)
  ```

  `scan()`'s existing `confirm_fn: Optional[Callable[[str], bool]]` parameter is reused
  unchanged — it's still "given prompt text, return bool"; it's now asked once per file
  instead of once per run. `--yes` (`assume_yes`) still bypasses every prompt.
- After synthesis, compute whether *everything* was declined (mirrors today's
  "declined at the manifest" outcome) without re-deriving bundles:
  `target_files = {r.target_file for r in guarded.records}`;
  `aborted = bool(target_files) and set(result.declined) == target_files`. When
  `aborted`, finish the run `RUN_FAILED` with `created=0` and return early, exactly as
  today's decline path does.
- Otherwise proceed exactly as today (drift, scoring, recording), using
  `result.proposals` — which now only contains proposals from bundles that were both
  confirmed and returned usable output.
- `ScanResult` gains `declined: Tuple[str, ...] = ()`, populated from
  `result.declined` on the non-aborted path too (so a partial run reports *which*
  files the operator skipped, distinct from `skipped`, which is model failures after
  retry).

### 4. `src/metaproject/cli.py::perform_scan`

- No signature changes (per-file `confirm_fn` still isn't CLI-exposed; the terminal
  prompt path continues to run through `guard._default_confirm` via `input()`, once per
  file instead of once per run).
- After the existing "aborted" / summary printing, add one more line distinguishing
  operator-skipped files from model-failed files:

  ```python
  if result.declined:
      console.print(f"[dim]Skipped by you: {', '.join(result.declined)}[/dim]")
  if result.skipped:
      console.print(
          f"[yellow]Run marked '{result.status}'. Skipped target files (model failed): "
          f"{', '.join(result.skipped)}[/yellow]"
      )
  ```

## What does *not* change

- `bundle_evidence()` / `chunk_bundle()` / the chunk-and-reduce machinery — untouched.
- `guard_evidence()` / redaction / exclusion — untouched; still the single egress
  chokepoint, still runs before any prompt.
- `confirm_send()` — untouched signature and behavior (kept for `guard.py`'s own
  tests and as a still-valid whole-manifest primitive), just no longer called from
  `scan()`.
- No `universe.db` schema change — `declined` is reporting-only, same as `skipped`
  is today (only run `status` is persisted).
- Agent-session refusal (`refuse_scan_in_agent_session`) is unaffected: `learn scan`
  is still refused outright for an agent session before any of this runs, so the new
  per-file prompts are only ever seen by an interactive human operator or a test's
  `confirm_fn`.

## Tests

- `tests/test_learn_synth.py`: add coverage for the new `confirm_fn` path on
  `synthesize()` — a bundle declined via `confirm_fn` produces no `runner` call, lands
  in `SynthResult.declined`, and a mixed accept/decline case yields calls only for the
  accepted bundle.
- `tests/test_learn_guard.py`: add `test_confirm_file_send_*` mirroring the existing
  `test_confirm_send_*` cases (bypassed by `--yes`, asks once, honors refusal, prompt
  names the target file).
- `tests/test_learn_apply.py::test_scan_declined_at_the_manifest_sends_nothing`: keep
  as-is — `confirm_fn=lambda _prompt: False` now declines every per-file prompt
  instead of the one whole-run prompt, but for a single project (`only=["atlas"]`) the
  net effect (`aborted is True`, `created == 0`, `runner` never called) is identical,
  so this test should pass unmodified and is the regression check for "decline
  everything still aborts".
- New test: a workspace producing evidence for ≥2 target files, `confirm_fn` that
  accepts one file and declines another — assert the accepted file's proposals are
  recorded, the declined file appears in `result.declined`, `result.aborted is False`,
  and the runner was never invoked for the declined file's evidence.
- Run the full suite (`pytest -q`) after — all `yes=True` call sites in
  `test_learn_apply.py`, `test_learn_drift.py`, `test_learn_tui.py`, `test_learn_score.py`
  bypass prompting entirely and should be unaffected.

## Docs

- `spec.md` §5.4.1/§7.4 and `README.md`'s "Before anything is sent" paragraph both
  describe a single whole-run manifest confirmation — update both to describe the
  per-file confirm loop once implemented.
