"""
Step 4 — Template Restructure (structure only, no content rewrite).

Takes raw body_html and normalises the heading hierarchy:
  - Multiple H1s → collapse to single H1 (keep first, demote rest to H2)
  - Missing H1 → insert one from the article title
  - Skipped heading levels (e.g. H2 → H4) → normalise to strict H1→H2→H3
  - Tags the introduction and conclusion sections so Claude can identify them

Output: normalised body_html with original text unchanged.
"""

import logging
import re
from typing import Any, Dict

from bs4 import BeautifulSoup, Comment, Tag

logger = logging.getLogger(__name__)

_CONCLUSION_KEYWORDS = {"conclusion", "summary", "résumé", "synthèse", "en résumé", "pour conclure"}


def normalize_html_structure(body_html: str, title: str) -> str:
    """
    Normalises the heading hierarchy of an article's body HTML without
    changing any text content.  Returns the corrected HTML string.
    """
    if not body_html or not body_html.strip():
        logger.warning("normalize_html_structure called with empty body_html.")
        return body_html or ""

    soup = BeautifulSoup(body_html, "lxml")

    # lxml wraps content in <html><body> — work inside <body>
    body = soup.find("body") or soup

    _fix_h1s(body, title)
    _normalise_levels(body)
    _tag_intro_and_conclusion(body)

    # Serialise just the inner content of <body>
    return body.decode_contents()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fix_h1s(body: Tag, title: str) -> None:
    """Ensures exactly one H1 exists."""
    h1_tags = body.find_all("h1")

    if not h1_tags:
        # Insert a new H1 before the first element
        h1 = body.new_tag("h1")
        h1.string = title
        first_child = next((c for c in body.children if isinstance(c, Tag)), None)
        if first_child:
            first_child.insert_before(h1)
        else:
            body.insert(0, h1)
        logger.debug("Inserted missing H1: '%s'", title)
        return

    # Keep the first H1; demote additional H1s to H2
    for extra_h1 in h1_tags[1:]:
        extra_h1.name = "h2"
        logger.debug("Demoted extra H1 '%s' to H2.", extra_h1.get_text(strip=True))


def _normalise_levels(body: Tag) -> None:
    """
    Ensures no heading level jump greater than 1 (e.g. H2 directly to H4).
    Iterates through all headings in document order and corrects each level
    based on the previous heading level.
    """
    heading_tags = body.find_all(re.compile(r"^h[1-6]$"))
    prev_level = 1  # we know there is exactly one H1 after _fix_h1s

    for tag in heading_tags:
        level = int(tag.name[1])
        if level > prev_level + 1:
            new_level = prev_level + 1
            logger.debug(
                "Normalising <%s> '%s' → <h%d>",
                tag.name,
                tag.get_text(strip=True)[:40],
                new_level,
            )
            tag.name = f"h{new_level}"
            level = new_level
        prev_level = level


def _tag_intro_and_conclusion(body: Tag) -> None:
    """
    Inserts HTML comments so Claude knows which sections are the introduction
    and conclusion.  Does not modify any text content.
    """
    all_tags = [t for t in body.children if isinstance(t, Tag)]
    if not all_tags:
        return

    # Introduction: content between H1 and the first H2
    h1 = body.find("h1")
    first_h2 = body.find("h2")

    if h1 and first_h2:
        h1.insert_before(Comment(" INTRODUCTION START "))
        first_h2.insert_before(Comment(" INTRODUCTION END "))

    # Conclusion: look for the last H2 whose text matches conclusion keywords
    h2_tags = body.find_all("h2")
    conclusion_h2 = None
    for h2 in reversed(h2_tags):
        text_lower = h2.get_text(strip=True).lower()
        if any(kw in text_lower for kw in _CONCLUSION_KEYWORDS):
            conclusion_h2 = h2
            break

    if conclusion_h2:
        conclusion_h2.insert_before(Comment(" CONCLUSION START "))
        # Insert closing comment after the last sibling of this section
        _insert_after_section(conclusion_h2)


def _insert_after_section(heading: Tag) -> None:
    """Inserts a CONCLUSION END comment after all content belonging to this heading."""
    node = heading.next_sibling
    last_content = heading
    while node:
        if isinstance(node, Tag) and re.match(r"^h[1-6]$", node.name):
            # Hit the next heading — insert before it
            node.insert_before(Comment(" CONCLUSION END "))
            return
        if isinstance(node, Tag):
            last_content = node
        node = node.next_sibling
    # No following heading — append at the end
    last_content.insert_after(Comment(" CONCLUSION END "))
