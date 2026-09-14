"""Structural heading matching for working deliverables (spec.md R-CLS-3, AC-2).

`headings()` is fence-aware (reuses `iter_sections`); `heading_matches()` decides
whether one project heading satisfies one template heading (same level, prefix match
on normalized text, `<...>` wildcard); `missing_headings()` reduces a template/project
pair to the template headings the project does not satisfy, order-insensitively and
one-to-one. Body text and extra project headings never affect the result.
"""

from metaproject.markdown import Heading, heading_matches, headings, missing_headings

# --------------------------------------------------------------------------- headings


def test_headings_ignores_headings_inside_fenced_code() -> None:
    text = "# Title\n\n```sh\n# not a heading\n```\n\n## Real\n"
    assert headings(text) == [Heading(level=1, title="Title"), Heading(level=2, title="Real")]


def test_headings_returns_level_and_title_in_document_order() -> None:
    text = "# Title\n\n## One\nalpha\n\n### One-a\nbeta\n\n## Two\ngamma\n"
    assert headings(text) == [
        Heading(level=1, title="Title"),
        Heading(level=2, title="One"),
        Heading(level=3, title="One-a"),
        Heading(level=2, title="Two"),
    ]


# ---------------------------------------------------------------------- heading_matches


def test_heading_matches_fails_on_level_mismatch() -> None:
    template = Heading(level=2, title="Implementation phases")
    project = Heading(level=3, title="Implementation phases")
    assert heading_matches(template, project) is False


def test_heading_matches_allows_a_project_title_prefixed_by_the_template_title() -> None:
    template = Heading(level=2, title="Implementation phases")
    project = Heading(level=2, title="Implementation phases (plan.md §2)")
    assert heading_matches(template, project) is True


def test_heading_matches_requires_the_template_text_as_a_prefix_not_a_substring() -> None:
    template = Heading(level=2, title="Implementation phases")
    project = Heading(level=2, title="Notes on Implementation phases")
    assert heading_matches(template, project) is False


def test_heading_matches_wildcard_placeholder_matches_any_title_at_that_level() -> None:
    template = Heading(level=1, title="<Title> — Spec")
    project = Heading(level=1, title="Widget Checkout — Spec")
    assert heading_matches(template, project) is True
    other = Heading(level=1, title="Anything Else")
    assert heading_matches(template, other) is True


def test_heading_matches_wildcard_still_requires_the_same_level() -> None:
    template = Heading(level=1, title="<Title> — Spec")
    project = Heading(level=2, title="Anything")
    assert heading_matches(template, project) is False


# ------------------------------------------------------------------- missing_headings


STATE_TEMPLATE = (
    "# Widget — STATE\n\n"
    "## Process\nsome process text\n\n"
    "## Verified facts (do not re-investigate)\n\n"
    "## Design invariants\n"
)


def test_ac2_removing_a_heading_from_a_state_like_doc_reports_it_missing() -> None:
    """AC-2: removing the heading makes it missing."""
    project = "# Widget — STATE\n\n## Process\nfilled in\n\n## Design invariants\nsome invariant\n"
    missing = missing_headings(STATE_TEMPLATE, project)
    assert missing == [Heading(level=2, title="Verified facts (do not re-investigate)")]


def test_ac2_renaming_a_heading_with_a_suffix_does_not_report_it_missing() -> None:
    """AC-2: `... — 2026` still starts with the template heading, so it satisfies it."""
    project = (
        "# Widget — STATE\n\n"
        "## Process\nfilled in\n\n"
        "## Verified facts (do not re-investigate) — 2026\nnoted\n\n"
        "## Design invariants\nsome invariant\n"
    )
    assert missing_headings(STATE_TEMPLATE, project) == []


def test_missing_headings_is_order_insensitive() -> None:
    template = "## Alpha\n\n## Beta\n"
    project = "## Beta\nbody\n\n## Alpha\nbody\n"
    assert missing_headings(template, project) == []


def test_missing_headings_is_one_to_one() -> None:
    """Two identical template headings require two distinct project headings."""
    template = "## Risks\n\n## Risks\n"
    project_with_one = "## Risks\nonly one\n"
    assert missing_headings(template, project_with_one) == [Heading(level=2, title="Risks")]

    project_with_two = "## Risks\nfirst\n\n## Risks\nsecond\n"
    assert missing_headings(template, project_with_two) == []


def test_missing_headings_ignores_extra_project_headings() -> None:
    template = "## Alpha\n"
    project = "## Alpha\nbody\n\n## Extra heading\nbody\n"
    assert missing_headings(template, project) == []


def test_missing_headings_ignores_body_text() -> None:
    template = "## Alpha\ntemplate body that will never appear verbatim\n"
    project = "## Alpha\ncompletely different body text\n"
    assert missing_headings(template, project) == []


def test_missing_headings_wildcard_title_never_reports_missing() -> None:
    template = "# <Title> — Spec\n\n## Body\n"
    project = "# Anything At All — Spec\n\n## Body\n"
    assert missing_headings(template, project) == []
