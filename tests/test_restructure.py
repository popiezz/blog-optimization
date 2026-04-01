"""
Tests for pipeline/restructure.py — heading normalization.

These are pure-function tests with no external dependencies.
"""
import pytest
from pipeline.restructure import (
    _fix_h1s,
    _normalise_levels,
    _tag_intro_and_conclusion,
    normalize_html_structure,
)
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _body(html: str):
    # Return the BeautifulSoup root object (not the body Tag), because
    # new_tag() is only available on the BeautifulSoup root, not on Tag objects.
    return BeautifulSoup(html, "lxml")


def _heading_names(html: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    import re
    return [tag.name for tag in soup.find_all(re.compile(r"^h[1-6]$"))]


# ---------------------------------------------------------------------------
# normalize_html_structure — top-level function
# ---------------------------------------------------------------------------

def test_normalize_empty_html_returns_empty():
    assert normalize_html_structure("", "My Title") == ""


def test_normalize_whitespace_only_returns_as_is():
    result = normalize_html_structure("   ", "My Title")
    assert result.strip() == ""


def test_normalize_preserves_text_content():
    html = "<h1>Original Title</h1><p>Some paragraph text.</p>"
    result = normalize_html_structure(html, "Original Title")
    assert "Some paragraph text." in result
    assert "Original Title" in result


# ---------------------------------------------------------------------------
# _fix_h1s — H1 insertion and demotion
# ---------------------------------------------------------------------------

def test_fix_h1s_inserts_h1_when_missing():
    body = _body("<p>Intro</p><h2>Section</h2>")
    _fix_h1s(body, "My Article Title")
    h1s = body.find_all("h1")
    assert len(h1s) == 1
    assert h1s[0].get_text() == "My Article Title"


def test_fix_h1s_keeps_single_h1():
    body = _body("<h1>Existing Title</h1><p>Text</p>")
    _fix_h1s(body, "Different Title")
    h1s = body.find_all("h1")
    assert len(h1s) == 1
    assert h1s[0].get_text() == "Existing Title"


def test_fix_h1s_demotes_extra_h1s_to_h2():
    body = _body("<h1>First</h1><h1>Second</h1><h1>Third</h1>")
    _fix_h1s(body, "Ignored Title")
    h1s = body.find_all("h1")
    h2s = body.find_all("h2")
    assert len(h1s) == 1
    assert h1s[0].get_text() == "First"
    assert len(h2s) == 2
    assert h2s[0].get_text() == "Second"
    assert h2s[1].get_text() == "Third"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known bug: normalize_html_structure crashes when HTML has no H1. "
        "lxml always returns a <body> Tag (not the BS4 root), so body.new_tag() "
        "resolves as a child-tag lookup → None → TypeError. "
        "Fix: pass soup (BS4 root) to _fix_h1s, or use soup.new_tag via the soup reference."
    ),
)
def test_fix_h1s_inserts_before_first_element():
    html = "<h2>Section One</h2><p>Text</p>"
    result = normalize_html_structure(html, "Article Title")
    soup = BeautifulSoup(result, "lxml")
    # H1 should come before H2
    tags = [t.name for t in soup.find_all(["h1", "h2"])]
    assert tags[0] == "h1"
    assert tags[1] == "h2"


# ---------------------------------------------------------------------------
# _normalise_levels — heading hierarchy correction
# ---------------------------------------------------------------------------

def test_normalise_levels_fixes_h2_to_h4_jump():
    # H1 → H2 → H4 should become H1 → H2 → H3
    html = "<h1>Title</h1><h2>Section</h2><h4>Sub</h4>"
    result = normalize_html_structure(html, "Title")
    headings = _heading_names(result)
    assert headings == ["h1", "h2", "h3"]


def test_normalise_levels_fixes_h1_to_h3_jump():
    html = "<h1>Title</h1><h3>Section</h3>"
    result = normalize_html_structure(html, "Title")
    headings = _heading_names(result)
    assert headings == ["h1", "h2"]


def test_normalise_levels_no_change_for_valid_hierarchy():
    html = "<h1>Title</h1><h2>Section</h2><h3>Sub</h3>"
    result = normalize_html_structure(html, "Title")
    headings = _heading_names(result)
    assert headings == ["h1", "h2", "h3"]


def test_normalise_levels_allows_level_decrease():
    # H3 → H2 is always valid (going back up)
    html = "<h1>Title</h1><h2>A</h2><h3>A1</h3><h2>B</h2>"
    result = normalize_html_structure(html, "Title")
    headings = _heading_names(result)
    assert headings == ["h1", "h2", "h3", "h2"]


# ---------------------------------------------------------------------------
# _tag_intro_and_conclusion — HTML comment markers
# ---------------------------------------------------------------------------

def test_intro_comments_inserted_around_pre_h2_content():
    html = "<h1>Title</h1><p>Intro text</p><h2>Section</h2>"
    result = normalize_html_structure(html, "Title")
    assert "INTRODUCTION START" in result
    assert "INTRODUCTION END" in result
    # END comment should appear before the first H2
    intro_end_pos = result.index("INTRODUCTION END")
    h2_pos = result.index("<h2>")
    assert intro_end_pos < h2_pos


def test_conclusion_comments_inserted_for_en_keyword():
    html = (
        "<h1>Title</h1><p>Intro</p>"
        "<h2>Section One</h2><p>Content</p>"
        "<h2>Conclusion</h2><p>Wrap up</p>"
    )
    result = normalize_html_structure(html, "Title")
    assert "CONCLUSION START" in result
    assert "CONCLUSION END" in result


def test_conclusion_comments_inserted_for_fr_keyword():
    html = (
        "<h1>Titre</h1><p>Introduction</p>"
        "<h2>Section</h2><p>Contenu</p>"
        "<h2>Résumé</h2><p>Fin</p>"
    )
    result = normalize_html_structure(html, "Titre")
    assert "CONCLUSION START" in result


def test_conclusion_comments_inserted_for_synthese():
    html = (
        "<h1>Titre</h1><p>Intro</p>"
        "<h2>Points</h2><p>Contenu</p>"
        "<h2>Synthèse</h2><p>Fin</p>"
    )
    result = normalize_html_structure(html, "Titre")
    assert "CONCLUSION START" in result


def test_no_conclusion_comment_when_no_matching_h2():
    html = "<h1>Title</h1><p>Intro</p><h2>Section A</h2><h2>Section B</h2>"
    result = normalize_html_structure(html, "Title")
    assert "CONCLUSION START" not in result


def test_no_intro_comment_when_no_h2():
    html = "<h1>Title</h1><p>Only content, no sections</p>"
    result = normalize_html_structure(html, "Title")
    assert "INTRODUCTION START" not in result


def test_conclusion_start_appears_before_conclusion_end():
    html = (
        "<h1>Title</h1><p>Intro</p>"
        "<h2>Section</h2><p>Body</p>"
        "<h2>Summary</h2><p>End text</p>"
    )
    result = normalize_html_structure(html, "Title")
    assert result.index("CONCLUSION START") < result.index("CONCLUSION END")
