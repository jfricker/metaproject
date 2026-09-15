"""Markdown heading parsing shared by `review`, `learn.collect` and `learn.apply`.

`Section`, `iter_sections`, and `normalize_heading` moved here from
`metaproject.learn.apply` (which re-imports them, so existing imports keep working)
because working-deliverable structure checking (R-CLS-3) needs the same fence-aware
heading parsing that `learn.apply` uses to splice proposals into a template.

`headings`, `heading_matches`, and `missing_headings` build on that parsing to answer
one question: does a project document still carry every heading its template expects?
Body text and extra project headings never enter that answer (R-CLS-3).
"""

import re
from dataclasses import dataclass
from typing import List, Tuple

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Section:
    """One Markdown heading and the extent of the content beneath it."""

    title: str
    level: int
    heading: int
    """Index of the heading line."""
    end: int
    """Index one past the section's last content line."""


def normalize_heading(text: str) -> str:
    """Reduce a heading to its identity: no hashes, no case, no spacing noise.

    Matching is exact on this normalized form and nothing looser. A fuzzy match is
    exactly the silent misplacement R7 is about.
    """
    stripped = (text or "").strip()
    match = _HEADING_RE.match(stripped)
    if match:
        stripped = match.group(2)
    else:
        stripped = stripped.lstrip("#").strip()
    return " ".join(stripped.split()).casefold()


def iter_sections(text: str) -> List[Section]:
    """Every heading in a Markdown document, with the extent of its content.

    A section ends at the next heading of the same or a shallower level, or at end of
    file. Headings inside a fenced code block are comments, not structure.
    """
    lines = text.split("\n")
    headings: List[Tuple[int, int, str]] = []
    fenced = False
    for index, line in enumerate(lines):
        if _FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))

    sections: List[Section] = []
    for position, (index, level, title) in enumerate(headings):
        end = len(lines)
        for next_index, next_level, _next_title in headings[position + 1 :]:
            if next_level <= level:
                end = next_index
                break
        sections.append(Section(title=title, level=level, heading=index, end=end))
    return sections


# ------------------------------------------------------------------- structure checks


@dataclass(frozen=True)
class Heading:
    """A heading's identity for structural matching: level and title only."""

    level: int
    title: str


def headings(text: str) -> List[Heading]:
    """Every heading in a document, fence-aware, as `Heading(level, title)`."""
    return [Heading(level=section.level, title=section.title) for section in iter_sections(text)]


def heading_matches(template: Heading, project: Heading) -> bool:
    """Does `project` satisfy the template heading `template` (R-CLS-3)?

    Same level, and the project's normalized title starts with the template's
    normalized title. A template title containing a `<...>` placeholder (e.g.
    `<Title> -- Spec`) matches any title at the same level.
    """
    if template.level != project.level:
        return False
    if "<" in template.title and ">" in template.title:
        return True
    normalized_template = normalize_heading(template.title)
    normalized_project = normalize_heading(project.title)
    return normalized_project.startswith(normalized_template)


def missing_headings(template_text: str, project_text: str) -> List[Heading]:
    """Template headings with no matching, unclaimed heading in the project text.

    Order-insensitive and one-to-one: each project heading can satisfy at most one
    template heading, so two identical template headings require two project headings.
    """
    project_headings = headings(project_text)
    claimed = [False] * len(project_headings)
    missing: List[Heading] = []
    for template_heading in headings(template_text):
        matched = False
        for index, project_heading in enumerate(project_headings):
            if claimed[index]:
                continue
            if heading_matches(template_heading, project_heading):
                claimed[index] = True
                matched = True
                break
        if not matched:
            missing.append(template_heading)
    return missing
