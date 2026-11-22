"""Report layout: outline, chapter choice, numbering, cover and contents (no Qt)."""

from __future__ import annotations

from opensees_studio.services.report_layout import (
    PLACEHOLDER,
    ReportOptions,
    compose_report,
    page_placeholder,
    report_outline,
    slug,
)

BODY = (
    "<h1>Bridge</h1><p>Intro</p><table><tr><td>x</td></tr></table>"
    "<h3>Revisions</h3><table></table>"
    "<h2>Model</h2><table></table>"
    "<h2>Results — Dead</h2><p>run</p>"
    "<h3>Peak displacements</h3><table></table>"
    "<h3>Reactions (supports)</h3><table></table><table></table>"
    "<h2>Results — Live</h2>"
    "<h3>Peak displacements</h3><table></table>"
    "<h2>Model</h2><p>again</p>"
)


def test_slug_is_ascii_lowercase_with_dashes() -> None:
    assert slug("Results — Dead") == "results-dead"
    assert slug("Fundación ACI 318-19") == "fundacion-aci-318-19"
    assert slug("———") == "section"


def test_outline_lists_chapters_and_subsections_after_the_preamble() -> None:
    outline = report_outline(BODY)
    assert [(s.key, s.level, s.parent, s.tables) for s in outline] == [
        ("model", 2, None, 1),
        ("results-dead", 2, None, 0),
        ("results-dead/peak-displacements", 3, "results-dead", 1),
        ("results-dead/reactions-supports", 3, "results-dead", 2),
        ("results-live", 2, None, 0),
        ("results-live/peak-displacements", 3, "results-live", 1),
        ("model-2", 2, None, 0),
    ]
    assert outline[1].title == "Results — Dead"


def test_cover_contents_and_numbering() -> None:
    page = compose_report(BODY, title="Bridge — report", style="")
    assert page.startswith("<!doctype html>") and page.endswith("</body></html>")
    cover, rest = page.split('<div class="contents">', 1)
    assert '<div class="cover">' in cover and "Revisions" in cover
    assert 'class="cover-title">Bridge</h1>' in cover
    assert '<a href="#s1">1&nbsp;&nbsp;Model</a>' in rest
    assert '<a href="#s4">2.2&nbsp;&nbsp;Reactions (supports)</a>' in rest
    assert '<a name="s4">2.2&nbsp;&nbsp;Reactions (supports)</a></h3>' in rest
    # The first chapter after the contents opens a new page.
    assert '<h2 style="page-break-before: always"><a name="s1">' in rest
    assert PLACEHOLDER.search(page) is None


def test_excluding_a_chapter_takes_its_subsections_with_it() -> None:
    options = ReportOptions(excluded=frozenset({"results-dead", "results-live/peak-displacements"}))
    page = compose_report(BODY, title="t", style="", options=options)
    assert "Reactions (supports)" not in page and "Results — Dead" not in page
    assert "Results — Live" in page and "Peak displacements" not in page
    assert '<a name="s2">2&nbsp;&nbsp;Results — Live</a>' in page


def test_plain_layout_keeps_the_preamble_on_top_without_numbers() -> None:
    options = ReportOptions(cover=False, contents=False, number_headings=False)
    page = compose_report(BODY, title="t", style="", options=options)
    assert 'class="cover"' not in page and "Contents" not in page
    assert "<h1>Bridge</h1>" in page
    assert '<h2><a name="s1">Model</a></h2>' in page


def test_paged_contents_carry_page_placeholders() -> None:
    page = compose_report(BODY, title="t", style="", paged=True)
    assert page_placeholder("s1") in page and 'href="#s1"' not in page
    assert {m.group(1) for m in PLACEHOLDER.finditer(page)} == {f"s{i}" for i in range(1, 8)}


def test_chapter_page_break_and_everything_left_out() -> None:
    options = ReportOptions(cover=False, contents=False, chapter_page_break=True)
    page = compose_report(BODY, title="t", style="", options=options)
    assert page.count('<h2 style="page-break-before: always">') == 4
    every = frozenset(s.key for s in report_outline(BODY) if s.level == 2)
    page = compose_report(BODY, title="t", style="", options=ReportOptions(excluded=every))
    assert "Every section is left out of this report." in page
