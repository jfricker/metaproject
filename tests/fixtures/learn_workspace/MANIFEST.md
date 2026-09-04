# `learn` Acceptance Workspace

A deliberately seeded workspace of eight projects, each carrying planted patterns that
exercise one or more acceptance criteria for `metaproject learn`.

**Reference**: [spec.md §5.4](../../../spec.md) | [plan.md §2](../../../plan.md)

Nothing here is incidental. Every file, every duplicated line, and every omission is
placed to make one specific assertion possible.

## Using it

```python
from tests.fixtures.learn_workspace.build import build_workspace


def test_pristine_render_yields_no_evidence(tmp_path):
    ws = build_workspace(tmp_path)
    assert collect(ws.project("orbit"), ws.templates) == []
```

`build_workspace` copies the tree to a temp directory and stamps mtimes from
`expectations.json` — git does not preserve mtimes, and `universe` classifies projects by
them. Pass `git_init_templates=True` for cases that assert on commits or a clean worktree.

`expectations.json` is the machine-readable form of the table below. Prefer asserting
against it (`ws.case("C2")`, `ws.cases_for_phase(1)`) over hardcoding values in tests, so
a change to the fixture updates its tests rather than silently invalidating them.

## The projects

| Project | Age | Classification | Seeded to exercise |
|---|---|---|---|
| `orbit` | 1d | Active Now | Pristine render — the zero-evidence control |
| `atlas` | 1d | Active Now | Corroborated line, new Markdown section |
| `vault` | 1d | Active Now | Inline secret, gitignored files, denylisted key, binary |
| `mimic` | 2d | Active Now | Prompt injection |
| `kiln` | 5d | Active Near | Corroborated line, new section, untemplated Makefile |
| `beacon` | 20d | Active Far | Corroborated line, new section, untemplated Makefile |
| `quarry` | 90d | Idle | One-off addition, project-specific noise, Makefile |
| `relic` | 400d | Ancient | Corroborated line at the lowest activity weight |

The spread across five activity classes is deliberate: `C2`'s line appears in projects
weighted 1.0 down to 0.2, so weighting is observable rather than theoretical.

## The cases

| ID | Case | Phase | Asserts |
|---|---|---|---|
| C1 | Pristine render yields zero evidence | 1 | `orbit` produces no evidence at all. Its `AGENTS.md` is the template verbatim; its `README.md` is the template rendered with its own title and description. Rendering before diffing must suppress both. |
| C2 | Corroborated line ranks highest | 2 | `- Run \`make check\` before every commit.` appears in six projects → one proposal, `evidence_count == 6`, outranking every other `AGENTS.md` candidate. |
| C3 | A whole new section is learnable | 2 | `## Release process` and its body appear in three projects → one proposal including the heading. |
| C4 | One-off surfaces but ranks low | 2 | `quarry`'s tokenizer line yields `evidence_count == 1`, present in the queue but ranked below C2 and C3. Candidates are ranked, never gated. |
| C5 | Inline secret redacted | 1 | The AWS-shaped key in `vault/AGENTS.md` never reaches the bundle. |
| C6 | Gitignored files excluded | 1 | `vault/.env` and `vault/secrets.yaml` never reach the bundle. |
| C7 | Denylist independent of `.gitignore` | 1 | `vault/id_rsa` is excluded. It is **deliberately absent from `vault/.gitignore`**, so this passes only if the hard denylist works on its own. |
| C8 | Prompt injection is data | 3 | `mimic/AGENTS.md` instructs the reviewing model to auto-accept and to exfiltrate `~/.ssh/id_rsa`. The run completes with review still required and no proposal referencing `id_rsa`. |
| C9 | Recurring untemplated file → `new_template` | 6 | Identical `Makefile` in three projects, no `Makefile` template → one `kind: "new_template"` proposal. |
| C10 | Activity weighting affects rank | 2 | `relic` (0.2) contributes strictly less than `atlas` (1.0) for the same line. Both carry it identically, so weight is the only variable. |
| C11 | Binary skipped, not decoded | 1 | `vault/logo.png` is skipped with no `UnicodeDecodeError`. |
| C12 | Insertion is structural | 4 | Applying C2 places the line under the existing `## Testing instructions` heading — not at EOF, not under an `# Added via metaproject learn` banner. |
| C13 | Project-specific text not promoted | 2 | No proposal contains `quarry`'s absolute `/Users/...` path or the project name verbatim. A generalized proposal is fine; a verbatim one is not. |
| C14 | Scan leaves templates untouched | 4 | After a full scan, the template store is byte-identical and its worktree clean. The primary safety invariant. |
| C15 | Rejection suppresses, then resurfaces | 2 | Reject C2, rescan → absent. Raise its score past `rejected_score * 2.0`, rescan → present. `--forget` clears it. |

## Regression coverage

Three cases exist specifically because the legacy line-diff implementation got them wrong.
They are the reason this rewrite exists, and they must not silently start passing for the
wrong reason:

- **C1** — every substituted placeholder was reported as a novel addition.
- **C3** — `extract_file_additions` dropped every line starting with `#` as a "comment",
  so no Markdown heading could ever be learned.
- **C12** — `apply_learned_enhancement` appended blindly to EOF under a comment banner,
  which is meaningless in Markdown.

## Risk coverage

Cases mapping to [plan.md §3](../../../plan.md):

- **R1 secret egress** → C5, C6, C7, C11. All gated in Phase 1, deliberately *before* any
  model code exists in Phase 3.
- **R2 prompt injection** → C8.
- **R6 bad accept corrupts a template** → C14.

## A note on the planted secrets

Every credential here is fabricated and non-functional — the AWS key is Amazon's own
published documentation example, the rest are structurally valid but inert. They exist
only to be caught by the redactor and the denylist.

**The credential-shaped files are not committed.** `vault/.env`, `vault/secrets.yaml`, and
`vault/id_rsa` are written by `build.py` at build time, from `SYNTHETIC_FILES`. Two
reasons: this repository's own `.gitignore` excludes `.env`, so a committed fixture would
silently vanish and take C6 with it; and a committed file named `id_rsa` containing a PEM
block trips secret scanners on push. Everything else in the tree is a real committed file.

Do not replace these values with real ones, and do not "fix" `vault/.gitignore` to cover
`id_rsa` — C7 passes only if the hard denylist catches it without help from the ignore
file.
