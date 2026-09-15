"""Tests for template engine, variable resolver, transformation, and binary safety."""

from pathlib import Path

from metaproject.config import Config
from metaproject.templates import (
    RenderReport,
    find_unknown_placeholders,
    is_binary_file,
    preprocess_template_string,
    render_template_string,
    render_template_tree,
    transform_template_name,
)
from metaproject.variables import collect_variables, resolve_author, slugify, titlecase


def test_titlecase_and_slugify() -> None:
    """Verify string normalization utilities."""
    assert titlecase("my-awesome_project") == "My Awesome Project"
    assert titlecase("api-service-v2") == "Api Service V2"
    assert titlecase("simple") == "Simple"

    assert slugify("My Awesome Project") == "my-awesome-project"
    assert slugify("Api_Service! V2") == "api-service-v2"
    assert slugify("---already-clean---") == "already-clean"


def test_resolve_author() -> None:
    """Verify author precedence resolution."""
    cfg = Config(author="Config Author")
    # CLI flag overrides config
    assert resolve_author("CLI Author", cfg) == "CLI Author"
    # Config overrides git/env
    assert resolve_author(None, cfg) == "Config Author"


def test_collect_variables() -> None:
    """Verify standard variable dictionary collection."""
    cfg = Config(author="Bob Tester")
    vars_dict = collect_variables(
        project_name="my_proj",
        title="Custom Title",
        description="A great tool",
        author=None,
        config=cfg,
        interactive=False,
    )
    assert vars_dict["ProjectTitle"] == "Custom Title"
    assert vars_dict["ProjectSlug"] == "my-proj"
    assert vars_dict["ProjectDescription"] == "A great tool"
    assert vars_dict["Author"] == "Bob Tester"
    assert "Date" in vars_dict
    assert "Year" in vars_dict


def test_transform_template_name() -> None:
    """Verify stripping of .template across patterns."""
    assert transform_template_name("AGENTS.template.md") == "AGENTS.md"
    assert transform_template_name(".gitignore.template") == ".gitignore"
    assert transform_template_name("docs.template") == "docs"
    assert transform_template_name("README.template.rst") == "README.rst"
    assert transform_template_name("unaffected.txt") == "unaffected.txt"


def test_preprocess_and_render_whitelisted_vars() -> None:
    """Verify substitution of whitelisted vars while preserving other braces."""
    template_text = (
        "# {ProjectTitle}\n"
        "By {Author} in {Year}.\n"
        'JSON block: {"name": "test", "id": 123}\n'
        'Shell script: echo "${USER}"\n'
        "CSS block: body { margin: 0; }\n"
    )
    variables = {
        "ProjectTitle": "Rocket Ship",
        "Author": "Commander",
        "Year": "2026",
    }

    preprocessed = preprocess_template_string(template_text)
    assert "{{ ProjectTitle }}" in preprocessed
    assert "{{ Author }}" in preprocessed
    assert "{{ Year }}" in preprocessed
    # Ensure unwhitelisted braces were NOT changed to Jinja expressions
    assert '{"name": "test", "id": 123}' in preprocessed
    assert "${USER}" in preprocessed

    rendered = render_template_string(template_text, variables)
    assert "# Rocket Ship\nBy Commander in 2026." in rendered
    assert '{"name": "test", "id": 123}' in rendered
    assert 'echo "${USER}"' in rendered
    assert "body { margin: 0; }" in rendered


def test_render_template_tree_with_binaries_and_empty_dirs(tmp_path: Path) -> None:
    """Verify full template tree rendering, name transformations, binary safety, and empty dirs."""
    source_dir = tmp_path / "templates_src"
    source_dir.mkdir()

    # Create text template
    (source_dir / "README.template.md").write_text(
        "# {ProjectTitle}\n{ProjectDescription}", encoding="utf-8"
    )

    # Create dotfile template
    (source_dir / ".gitignore.template").write_text("*.log\n.venv/", encoding="utf-8")

    # Create directory with .template suffix
    docs_dir = source_dir / "docs.template"
    docs_dir.mkdir()
    (docs_dir / "guide.template.md").write_text("Guide for {ProjectTitle}", encoding="utf-8")

    # Create binary file with null byte
    binary_file = source_dir / "logo.png"
    binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    binary_file.write_bytes(binary_data)
    assert is_binary_file(binary_file)

    # Destination
    target_dir = tmp_path / "rendered_output"
    vars_dict = {
        "ProjectTitle": "Alpha Flight",
        "ProjectDescription": "Supersonic software",
    }

    report = render_template_tree(source_dir, target_dir, vars_dict, dry_run=False)
    created = report.paths
    assert len(created) >= 4

    assert (target_dir / "README.md").exists()
    assert "# Alpha Flight\nSupersonic software" == (target_dir / "README.md").read_text(
        encoding="utf-8"
    )

    assert (target_dir / ".gitignore").exists()
    assert (target_dir / "docs" / "guide.md").exists()
    assert "Guide for Alpha Flight" == (target_dir / "docs" / "guide.md").read_text(
        encoding="utf-8"
    )

    assert (target_dir / "logo.png").exists()
    assert (target_dir / "logo.png").read_bytes() == binary_data


def test_find_unknown_placeholders_ignores_whitelisted_and_foreign_syntax() -> None:
    """Whitelisted vars, jinja passthrough, shell vars, and JSON braces are not reported."""
    text = (
        "Hello {ProjectTitle}, by {Author}.\n"
        "Typo appears twice: {projcet} and again {projcet}.\n"
        "Jinja passthrough: {{ jinja }}\n"
        "Shell: echo ${SHELL}\n"
        'JSON block: { "name": "test", "id": 123 }\n'
        "Spaced braces: { id }\n"
    )

    assert find_unknown_placeholders(text) == ["projcet"]


def test_render_template_tree_reports_unknown_placeholder_warning(tmp_path: Path) -> None:
    """A template with an unwhitelisted placeholder produces a named warning."""
    source_dir = tmp_path / "store"
    source_dir.mkdir()
    (source_dir / "AGENTS.template.md").write_text(
        "# {ProjectTitle}\nWelcome to {projcet}.", encoding="utf-8"
    )
    target_dir = tmp_path / "out"

    report = render_template_tree(source_dir, target_dir, {"ProjectTitle": "Alpha"})

    assert isinstance(report, RenderReport)
    assert (target_dir / "AGENTS.md").exists()
    assert report.warnings == ["AGENTS.template.md: unknown placeholder {projcet}"]


def test_render_template_tree_excludes_file_and_directory(tmp_path: Path) -> None:
    """`exclude` skips a named file and an entire named directory's subtree."""
    source_dir = tmp_path / "store"
    source_dir.mkdir()
    (source_dir / "HANDOFF.template.md").write_text("Handoff notes", encoding="utf-8")
    (source_dir / "AGENTS.template.md").write_text("# {ProjectTitle}", encoding="utf-8")
    archive_dir = source_dir / "docs.template" / "archive.template"
    archive_dir.mkdir(parents=True)
    (archive_dir / ".gitkeep.template").write_text("", encoding="utf-8")
    (archive_dir / "notes.template.md").write_text("notes", encoding="utf-8")
    target_dir = tmp_path / "out"

    report = render_template_tree(
        source_dir,
        target_dir,
        {"ProjectTitle": "Alpha"},
        exclude={"HANDOFF.md", "docs/archive"},
    )

    rendered_names = {p.relative_to(target_dir).as_posix() for p in report.paths}
    assert "HANDOFF.md" not in rendered_names
    assert not any(name.startswith("docs/archive") for name in rendered_names)
    assert not (target_dir / "HANDOFF.md").exists()
    assert not (target_dir / "docs" / "archive").exists()
    assert (target_dir / "AGENTS.md").exists()


def test_render_template_tree_dry_run_still_reports_paths(tmp_path: Path) -> None:
    """dry_run=True reports the same planned paths without writing anything."""
    source_dir = tmp_path / "store"
    source_dir.mkdir()
    (source_dir / "README.template.md").write_text("# {ProjectTitle}", encoding="utf-8")
    target_dir = tmp_path / "out"

    report = render_template_tree(source_dir, target_dir, {"ProjectTitle": "Alpha"}, dry_run=True)

    assert report.paths == [target_dir / "README.md"]
    assert not (target_dir / "README.md").exists()
