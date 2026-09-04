"""Egress guard tests: ignore filtering, denylist, redaction, send manifest.

plan.md Phase 1 gate and spec.md §7.4. Acceptance cases: C5, C6, C7, C11, C20, C24.
This is risk R1, tested deliberately before any model code exists. No model is
involved anywhere in this module.
"""

from pathlib import Path

import pytest

from metaproject.learn.collect import collect_project, collect_workspace
from metaproject.learn.guard import (
    REDACTION_PLACEHOLDER,
    GitignoreMatcher,
    build_manifest,
    confirm_send,
    contains_secret,
    exclusion_reason,
    filter_paths,
    guard_evidence,
    is_denylisted,
    redact,
)
from tests.fixtures.learn_workspace.build import build_workspace

AWS_SECRET = "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY"
GIT_SHA = "3f7a1c9e4b2d8a6f0c5e1b9d7a3f2c8e4b6d0a91"
UUID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
BASE64_VECTOR = "SGVsbG8sIE1ldGFQcm9qZWN0IQ=="


@pytest.fixture
def workspace(tmp_path: Path):
    """Materialize the learn acceptance workspace."""
    return build_workspace(tmp_path)


# --------------------------------------------------------------------------- .gitignore parsing


def test_gitignore_matcher_parses_without_a_git_repository(workspace) -> None:
    """C24: vault has a .gitignore but no .git; the file must be parsed, not delegated."""
    vault = workspace.project("vault")
    assert not (vault / ".git").exists()

    matcher = GitignoreMatcher.from_project(vault)
    assert matcher.match(".env")
    assert matcher.match("secrets.yaml")
    assert not matcher.match("AGENTS.md")


def test_gitignore_matcher_handles_git_backed_projects(workspace) -> None:
    """C24: the same parsing path serves atlas, which is a real repository."""
    atlas = workspace.project("atlas")
    assert (atlas / ".git").exists()

    matcher = GitignoreMatcher.from_project(atlas)
    assert matcher.match(".DS_Store")
    assert not matcher.match("AGENTS.md")


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("__pycache__/", "__pycache__/mod.pyc", True),
        ("__pycache__/", "src/__pycache__/mod.pyc", True),
        ("*.py[cod]", "mod.pyc", True),
        ("*.py[cod]", "mod.py", False),
        (".venv/", ".venv/bin/python", True),
        ("/build", "build/out", True),
        ("/build", "src/build/out", False),
        ("docs/*.tmp", "docs/a.tmp", True),
        ("docs/*.tmp", "docs/sub/a.tmp", False),
        ("**/logs", "a/b/logs/x.txt", True),
    ],
)
def test_gitignore_pattern_semantics(pattern: str, path: str, expected: bool) -> None:
    """Core gitignore semantics: dir-only, anchoring, character classes, globstar."""
    matcher = GitignoreMatcher([pattern])
    assert matcher.match(path) is expected


def test_gitignore_negation_reinstates_a_path() -> None:
    """A later `!` pattern un-ignores a previously ignored path."""
    matcher = GitignoreMatcher(["*.log", "!keep.log"])
    assert matcher.match("debug.log")
    assert not matcher.match("keep.log")


def test_gitignore_comments_and_blank_lines_ignored() -> None:
    """Comment and blank lines are not patterns."""
    matcher = GitignoreMatcher(["# a comment", "", "  ", "*.tmp"])
    assert matcher.match("x.tmp")
    assert not matcher.match("# a comment")


# --------------------------------------------------------------------------- C6, C7, C11, C24


def test_gitignored_files_never_reach_the_manifest(workspace) -> None:
    """C6: vault/.env and vault/secrets.yaml are excluded by the project's .gitignore."""
    vault = workspace.project("vault")
    assert (vault / ".env").exists()
    assert (vault / "secrets.yaml").exists()

    assert exclusion_reason(vault, ".env") is not None
    assert exclusion_reason(vault, "secrets.yaml") is not None


def test_denylist_applies_without_gitignore_help(workspace) -> None:
    """C7: vault/id_rsa is absent from vault/.gitignore; only the denylist catches it."""
    vault = workspace.project("vault")
    assert (vault / "id_rsa").exists()
    assert "id_rsa" not in (vault / ".gitignore").read_text(encoding="utf-8")
    assert not GitignoreMatcher.from_project(vault).match("id_rsa")

    assert exclusion_reason(vault, "id_rsa") == "denylist"


@pytest.mark.parametrize(
    "name",
    [".env", ".env.local", "server.pem", "signing.key", "id_rsa", "id_ed25519"],
)
def test_hard_denylist_names(name: str) -> None:
    """spec.md §7.4's hard denylist, matched on filename regardless of content."""
    assert is_denylisted(name)


def test_filter_paths_excludes_every_sensitive_vault_file(workspace) -> None:
    """C6 + C7 + C11 together: nothing sensitive survives the path filter."""
    vault = workspace.project("vault")
    candidates = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*") if p.is_file())
    kept, excluded = filter_paths(vault, candidates)

    excluded_paths = {rel for rel, _ in excluded}
    assert {".env", "secrets.yaml", "id_rsa", "logo.png"} <= excluded_paths
    assert ".env" not in kept
    assert "secrets.yaml" not in kept
    assert "id_rsa" not in kept
    assert "logo.png" not in kept
    assert "AGENTS.md" in kept


def test_binary_files_excluded_with_a_binary_reason(workspace) -> None:
    """C11: logo.png is excluded as binary rather than decoded."""
    vault = workspace.project("vault")
    assert exclusion_reason(vault, "logo.png") == "binary"


# ------------------------------------------------------------------ C20 (no over-redaction)


def test_documentation_named_secrets_md_is_not_excluded(workspace) -> None:
    """C20: cipher/secrets.md is documentation and must not be excluded on filename alone."""
    cipher = workspace.project("cipher")
    assert exclusion_reason(cipher, "secrets.md") is None


def test_soft_denylist_still_excludes_credential_bearing_files(tmp_path: Path) -> None:
    """The `*secret*` pattern still bites when the file actually carries a credential."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "secrets.md").write_text(
        f"api_secret_key: {AWS_SECRET}\n",
        encoding="utf-8",
    )
    assert exclusion_reason(project, "secrets.md") == "denylist"


def test_non_document_soft_matches_are_always_excluded(tmp_path: Path) -> None:
    """A `*secret*` match that is not a document is excluded without reading it."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "secrets.yaml").write_text("harmless: true\n", encoding="utf-8")
    assert exclusion_reason(project, "secrets.yaml") == "denylist"


@pytest.mark.parametrize("value", [GIT_SHA, UUID, BASE64_VECTOR])
def test_high_entropy_but_legitimate_content_survives(value: str) -> None:
    """C20: a git SHA, a UUID, and a base64 test vector must survive redaction."""
    text = f"- The value is {value} and it is not a secret.\n"
    assert redact(text) == text


def test_ordinary_prose_is_untouched() -> None:
    """Redaction is precise, not aggressive."""
    text = "- Run `make check` before every commit.\n## Release process\n"
    assert redact(text) == text


def test_cipher_evidence_survives_the_guard(workspace) -> None:
    """C20 end to end: cipher's three high-entropy values reach the manifest intact."""
    records = collect_project(workspace.project("cipher"), workspace.templates)
    result = guard_evidence(records)
    body = "\n".join(line for rec in result.records for line in rec.added_lines)
    assert GIT_SHA in body
    assert UUID in body
    assert BASE64_VECTOR in body


# --------------------------------------------------------------------------- C5 (redaction)


def test_inline_secret_is_redacted(workspace) -> None:
    """C5: the AWS-shaped key in vault/AGENTS.md never reaches the guard output."""
    records = collect_project(workspace.project("vault"), workspace.templates)
    assert any(AWS_SECRET in line for rec in records for line in rec.added_lines)

    result = guard_evidence(records)
    serialized = result.manifest.render() + "".join(rec.diff for rec in result.records)
    assert AWS_SECRET not in serialized


def test_redacted_line_survives_in_redacted_form(workspace) -> None:
    """C5: the surrounding line stays as evidence; only the credential is replaced."""
    records = collect_project(workspace.project("vault"), workspace.templates)
    result = guard_evidence(records)
    lines = [line for rec in result.records for line in rec.added_lines]
    hit = [line for line in lines if "Staging deploys" in line]
    assert len(hit) == 1
    assert REDACTION_PLACEHOLDER in hit[0]
    assert AWS_SECRET not in hit[0]


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_FakeFixtureTokenNeverRealAAAAAAAAAAAA",
        "sk_live_51H8xQ2LkdIwHu7ixNCDdVQnpFakeKeyForFixtures",
        "xoxb-123456789012-1234567890123-FakeSlackTokenValue",
    ],
)
def test_known_token_shapes_are_redacted(secret: str) -> None:
    """Known credential prefixes are redacted regardless of surrounding text."""
    text = f"deploy uses {secret} here\n"
    assert secret not in redact(text)
    assert REDACTION_PLACEHOLDER in redact(text)


def test_private_key_block_is_redacted() -> None:
    """A PEM private key block is redacted in full."""
    text = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAA\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
    )
    redacted = redact(text)
    assert "b3BlbnNzaC1rZXktdjEA" not in redacted
    assert REDACTION_PLACEHOLDER in redacted


def test_secret_named_assignment_is_redacted() -> None:
    """A value assigned to a secret-shaped key is redacted even at low entropy."""
    assert "hunter2" not in redact("password=hunter2\n")
    assert "abc" not in redact("github_token: abc\n")


def test_contains_secret_agrees_with_redact() -> None:
    """`contains_secret` is the predicate form of `redact`."""
    assert contains_secret(f"key={AWS_SECRET}")
    assert not contains_secret(f"commit {GIT_SHA}")


# --------------------------------------------------------------------------- manifest


def test_manifest_lists_exactly_what_would_be_sent(workspace) -> None:
    """Gate: the manifest enumerates precisely the guarded evidence, nothing more."""
    records = collect_workspace(workspace.projects, workspace.templates)
    result = guard_evidence(records)

    manifest_keys = {(e.project_path, e.target_file) for e in result.manifest.entries}
    record_keys = {(r.project_path, r.target_file) for r in result.records}
    assert manifest_keys == record_keys
    assert len(result.manifest.entries) == len(result.records)


def test_manifest_excludes_nothing_sensitive(workspace) -> None:
    """C5 + C6 + C7 + C11 on the whole workspace: the manifest is clean."""
    records = collect_workspace(workspace.projects, workspace.templates)
    result = guard_evidence(records)
    rendered = result.manifest.render()

    assert AWS_SECRET not in rendered
    for forbidden in (".env", "secrets.yaml", "id_rsa", "logo.png"):
        assert forbidden not in rendered


def test_manifest_render_names_projects_and_targets(workspace) -> None:
    """The operator can see project and target for every line about to leave the machine."""
    records = collect_project(workspace.project("kiln"), workspace.templates)
    manifest = build_manifest(guard_evidence(records).records, [])
    rendered = manifest.render()
    assert "kiln" in rendered
    assert "AGENTS.md" in rendered
    assert "Makefile" in rendered


def test_manifest_records_exclusions_with_reasons(workspace) -> None:
    """Excluded paths are reported with why, so the operator can audit the guard."""
    vault = workspace.project("vault")
    candidates = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*") if p.is_file())
    _, excluded = filter_paths(vault, candidates)
    manifest = build_manifest([], [(str(vault), rel, reason) for rel, reason in excluded])
    assert {"gitignore", "denylist", "binary"} <= {e.reason for e in manifest.excluded}


# --------------------------------------------------------------------------- confirmation


def test_confirm_send_bypassed_by_yes(workspace) -> None:
    """`--yes` bypasses the per-session confirmation for non-interactive use."""
    manifest = build_manifest([], [])

    def refuse(_prompt: str) -> bool:
        raise AssertionError("confirmation must not be requested under --yes")

    assert confirm_send(manifest, assume_yes=True, confirm_fn=refuse) is True


def test_confirm_send_asks_once_and_honors_refusal() -> None:
    """Without --yes the operator is asked, and a refusal stops the send."""
    manifest = build_manifest([], [])
    calls: list[str] = []

    def accept(prompt: str) -> bool:
        calls.append(prompt)
        return True

    assert confirm_send(manifest, confirm_fn=accept) is True
    assert len(calls) == 1

    assert confirm_send(manifest, confirm_fn=lambda _p: False) is False


# --------------------------------------------------------------------------- no model


def test_phase_one_involves_no_model() -> None:
    """Gate: neither Phase 1 module references the model or spawns a process."""
    from metaproject.learn import collect as collect_mod
    from metaproject.learn import guard as guard_mod

    for module in (collect_mod, guard_mod):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "claude" not in source.lower()
        assert "subprocess" not in source
