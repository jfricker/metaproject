# Ship project subagents as a deliverable — Design

**Author**: John Fricker.
**Derived from**: SPEC.md (2026-11-26, approved).
**Last updated**: 2026-11-26.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-26).

## Affected components

| Component | Change | Requirements |
|---|---|---|
| `src/metaproject/agents/*.md` (new package data) | The three project agents, without the `model` key | R-AGT-1–3 |
| `src/metaproject/learn/agents/learn-synthesizer.md` (new package data) | The internal agent | R-AGT-1, 23, 26 |
| `src/metaproject/subagents.py` (new) | Bundle declaration, classification, the single agent write path, and the report | R-AGT-1, 4–5, 9–14 |
| `src/metaproject/skills.py` | Manifest v3: `Manifest.agents`, load/render/write keep it. `skills.py` stays the writer of skills, and `_write_manifest` stays the only writer of the manifest file | R-AGT-7 |
| `src/metaproject/deliverables.py` | `DeliverableClass.SUBAGENT`, plus `subagent_paths()`. Not in `DELIVERABLES`, `scaffolded()` or `learn_targets()` | R-AGT-6 |
| `src/metaproject/scaffold.py`, `review.py` (`backfill_missing`) | After `install_project_skills`, call `subagents.install_project_agents` with the same tracker and `dry_run` | R-AGT-12 |
| `src/metaproject/cli.py` | `skills status|sync` (single and `--all`) also run the agent pass and render it. `review --format table|json` and `review --managed` | R-AGT-13–15, 22 |
| `src/metaproject/doctor.py` | `check_project_agents` after `check_project_skills` | R-AGT-16 |
| `src/metaproject/review.py` | `result_to_dict(ReviewResult)`. No change to auditing | R-AGT-17, 22 |
| `src/metaproject/learn/synth.py` | `claude_command`, `run_claude` (temp cwd), slimmer prompt shell, budget includes the system prompt | R-AGT-23–26 |
| `src/metaproject/sdlc_skills/` | Edit `backlog-factory`, `execute-tests`, add `review-fleet/` | R-AGT-18–20 |
| `src/metaproject/skill/` and README | Docs | R-AGT-21 |
| `scripts/gen_skill_history.py`, `skill_history.json` | `agents` section | R-AGT-8 |
| `pyproject.toml` | Package data gains `agents/**` and `learn/agents/**` | R-AGT-1 |
| `.claude/agents/` (this repository) | Prototypes deleted. This repository's own `skills sync` installs the shipped three | R-AGT-3 |

### `subagents.py`

```python
@dataclass(frozen=True)
class BundledAgent:
    name: str
    path: Path            # package file

def bundled_agents() -> Tuple[BundledAgent, ...]          # project agents only, sorted
def internal_agent_body(name: str) -> str                 # frontmatter-stripped body (learn)
def enabled_agents(home: Path) -> Tuple[Tuple[BundledAgent, ...], List[str]]  # (enabled, warnings)

@dataclass(frozen=True)
class AgentStatus:  name; state; installed_release; action=None; note=None
@dataclass
class AgentsReport: target: Path; statuses; warnings; notice=None; manifest_state=None

def inspect_project_agents(project_dir) -> AgentsReport
def sync_project_agents(project_dir, *, update=True, force=(), dry_run=False, tracker=None) -> AgentsReport
def install_project_agents(project_dir, dry_run=False, tracker=None)  # update=False
```

- **Home**: `skills.skills_home(project_dir)`. When it is `None` (the `root` sub-project
  has no home), the result is the same refusal notice that skills give, and nothing is written. The agents dir is
  `home/.claude/agents`.
- **States** reuse `skills.CURRENT/OUTDATED/MODIFIED/MISSING` and the action constants, plus
  `DISABLED = "disabled"` for a file present for a bundled name that `agents.enabled` excludes. That state is report-only.
- **Classification** (`classify_agent`): hash the file bytes, then:
  equal to the bundle → current; equal to the manifest entry's sha256 or any ledger digest →
  outdated; otherwise → modified; absent → missing. This mirrors `classify_skill`, but over one
  file rather than a `file_map`.
- **Write** (`_write_agent`): `os.lstat` the agents dir and refuse if it is a symlink.
  `mkdir(parents)` if absent (tracked as created). Write `.<name>.md.metaproject-tmp` in the same
  dir, `fsync`, re-hash and compare with the bundle, then `os.replace` into place. The tracker records a
  created or modified file. On any `OSError` the temp file is unlinked and the original
  is untouched. A single-file `os.replace` is atomic, so the directory-level swap
  `treeops.swap_tree` that skills use is not needed.
- **Manifest**: after the agent writes, load the manifest again, set `manifest.agents[name] =
  {release, sha256}` for every agent written or found current, and call `skills._write_manifest`.
  Skills and bridges entries pass through untouched. Writing a new manifest entry is the
  `RECORDED` action, as for skills.
- **force**: names are validated against `bundled_agents()` before any write. An unknown name
  raises `MetaProjectError`, as skills do. The CLI splits `--force` names between skills and
  agents by membership. A bundle test ensures the two sets are disjoint, so a name always belongs
  to exactly one.

### Manifest v3 (`skills.py`)

`MANIFEST_VERSION = 3`. `Manifest` gains `agents: Dict[str, Dict]`. `load_manifest` reads
`agents` when `version >= 3` and requires it to be a dict of `{release: str, sha256: hex}`
(otherwise `unreadable`). v1 and v2 load with `agents = {}`. `render_manifest` always emits
`agents` (empty `{}` included), so the first write after an upgrade produces a stable v3. Every
existing caller that passes a `Manifest` keeps the `agents` field. Callers that pass a bare dict
(skills-only) must now pass the loaded `Manifest`, so a skills pass can't erase agents. An
audit of `_write_manifest` callers is part of the plan.

### CLI

- `skills status`: one `inspect_project_agents` per project, after skills. The table adds an
  "Agents" section with the same columns and labels (`SKILL_STATE_LABELS` plus `disabled`).
  JSON adds top-level `agents` in single-project mode and per-project `agents` with `--all`.
  The exit code is computed over skills and agents together, using the same rule.
- `skills sync`: runs `sync_project_skills` then `sync_project_agents` with the same
  `update/dry_run`, and splits `force` by membership. The agent-session guard and TTY
  confirmation happen once, before either pass. With `--all`, a project fails (exit 1) if either
  pass raises, and the next project still runs.
- `review --format table|json`: with `json`, call `review_project`/`review_workspace` as the
  printed path does, and print `{"templates": str, "projects": [result_to_dict(r)]}` with
  `json.dumps(indent=2, sort_keys=True)`. `result_to_dict` uses `dataclasses.asdict` plus the
  derived properties and the board's compliance label (taken from the same function the board
  uses, so the two cannot diverge). `--format json` is a usage error combined with
  `--unignore` or `--list-ignored`. It forces the non-TUI path, and notices go to a stderr console.
- `review --managed`: reviews `catalog.managed_projects(cfg)` (the set `doctor` and
  `skills --all` use) instead of walking the filesystem. It is a usage error combined with
  `--all`, `--depth` or a `PROJECT` argument. It works with both formats. An empty catalog prints
  an empty board or `"projects": []` and exits 0. This is how R-AGT-20's per-project review runs
  (operator, 2026-11-26).

### Doctor

`check_project_agents(project_dir)` follows `check_project_skills`'s shape: problems are
`missing`/`outdated` names, and the fix is `sync_project_agents(update=True)` behind the
existing per-check confirmation (report-only in agent sessions). `modified` and `disabled` are
informational. Order: config, docs, skills legacy link, skills targets, project skills,
**project agents**, skill shadowing, hook scripts. The DESIGN-INVARIANTS ordering line is
amended to match (operator, 2026-11-26).

### learn

```python
def claude_command(claude_path, model) -> List[str]:
    argv = [claude_path, "-p", "--tools", "", "--strict-mcp-config",
            "--disable-slash-commands", "--system-prompt", synthesizer_prompt()]
    if model: argv += ["--model", model]
    return argv
```

- `synthesizer_prompt()` is cached and returns `subagents.internal_agent_body("learn-synthesizer")`,
  read through `importlib.resources`, with the frontmatter removed by splitting on the second `---` line.
- `run_claude` wraps the call in `tempfile.TemporaryDirectory(prefix="metaproject-synth-")`
  and passes `cwd=`. The prompt still goes on stdin.
- `_instructions(target, kind, strict)` becomes `TARGET: <file>`, `KIND: edit|new`,
  `MODE: map`, plus the strict prefix. `build_reduce_prompt` sends `MODE: reduce` and the fenced
  proposals. The rules and the reduce paragraph live only in the agent body.
- **Budget**: `chunk_bundle` subtracts `measure(synthesizer_prompt())` from the budget as well
  as head and tail, because the system prompt shares the model's context window.
- **Size**: the system prompt is about 4 KB in argv, far below argument-length limits. The
  evidence stays on stdin.

### Skills

- `backlog-factory`: step 6 launches `backlog-worker` with
  `Item/Worktree/Branch` when that agent type is available. Otherwise it pastes the existing
  brief. The brief stays in the skill as the fallback, and a test checks that each of its rules
  appears in the agent body.
- `execute-tests`: step 6 says to dispatch `spec-reviewer` when available, record
  `blocker` findings under STATE.md's unmet criteria, and treat `major` findings as items to
  fix before reporting. Otherwise it keeps the manual check.
- `review-fleet/SKILL.md`: a new orchestrator. It runs `metaproject review --managed --format json`
  once, filters out `is_clean` and ignored projects, dispatches `project-auditor` in parallel with
  each project's JSON entry, merges the reports into one table grouped by action, and writes
  nothing. Because it lives under `sdlc_skills/`, `bundled_skills()` picks it up automatically,
  and the ledger covers it.

## Data flow / interfaces

```mermaid
flowchart LR
  subgraph package
    A[agents/*.md] --> SA[subagents.py]
    L[learn/agents/learn-synthesizer.md] --> SY[learn/synth.py]
    H[skill_history.json<br/>skills + agents] --> SA
  end
  SA -- write via os.replace --> P[home/.claude/agents/name.md]
  SA -- agents section --> M[home/.agents/skills/.metaproject-skills.json v3]
  SK[skills.py] -- skills + bridges --> M
  CLI[skills status/sync] --> SK & SA
  DOC[doctor] --> SK & SA
  SCF[new / backfill / adopt] --> SK & SA
  SY -- "claude -p --tools '' --strict-mcp-config --system-prompt body (cwd=tmp)" --> C[(claude)]
  RF[review-fleet skill] -- review --format json --> RV[review.py]
  RF -- findings JSON --> PA[project-auditor]
```

Dependency direction: `subagents → skills` (manifest, home, constants, release helpers).
`skills` never imports `subagents`. Call sites compose the two passes.

## Alternatives considered

- **A generic "bundled asset" engine shared by skills and agents.** It would be cleaner in the long
  run, but it means refactoring the skills writer, bridges and their invariants in a cycle whose
  subject is agents. Rejected for v1. `subagents.py` is about 250 lines and reuses the manifest,
  ledger, home and release helpers.
- **Separate agents manifest/ledger.** Rejected by the operator (Q4/Q5). One manifest keeps
  `--all` reporting and `doctor` single-pass.
- **Calling the agent pass from inside `sync_project_skills`.** It would need `skills → subagents`
  (a cycle with `subagents → skills`) and hide a second write behind a skills function. Rejected. The
  call sites compose the passes explicitly. There are five of them (cli ×2, doctor, scaffold,
  backfill).
- **`--agents <file> --agent learn-synthesizer` for synth.** Rejected (concern 4). It layers the
  default Claude Code system prompt, which is written for tool use, on top. `--system-prompt` gives
  a clean judge.
- **Directory swap (`treeops.swap_tree`) per agent.** Unnecessary for one file. `os.replace` is
  atomic on POSIX and Windows for same-directory renames.
- **`review` JSON built from the board renderer.** Rejected. JSON comes from `ReviewResult`
  directly, and the compliance label from the board's classifier function.

## Trade-offs and risks

- **Forward incompatibility**: a v3 manifest read by an older metaproject is `newer`, so that
  release reports and won't sync. This is expected, and the same as the v1→v2 transition. Note it
  in the README upgrade line.
- **Manifest clobbering**: any remaining bare-dict `_write_manifest` caller would erase `agents`.
  Mitigation: change the signature to accept only `Manifest`, and test that a skills sync
  preserves an agents entry and that an agents sync preserves skills and bridges.
- **`DISABLED` vs user files**: a disabled bundled-name file is never touched, so turning an
  agent off leaves the file in place. That is deliberate (R-AGT-10). The status output says how
  to remove it.
- **Claude Code agent schema drift**: the `tools`, `disallowedTools` and `effort` keys may change. The
  frontmatter test pins what we ship, and nothing parses the frontmatter at run time except the
  strip in `internal_agent_body`.
- **Live tool-less check**: CI can't run `claude`. A unit test pins the argv. The live
  init-event check (acceptance criterion 14) is manual and goes to TODO.md.
- **Behaviour change in learn**: removing the default system prompt and project context may
  change proposal quality. The existing synth fixtures validate structure only. Run one real
  `metaproject learn scan` before release and compare (also in TODO.md).
- **Ledger growth**: one entry per agent per release, which is negligible.

## Open questions

None. Resolved by the operator on 2026-11-26: `review-fleet` uses a new `review --managed` flag,
and the doctor agents check runs right after project skills.
