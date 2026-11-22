"""Page layout of the calculation report: cover, contents, numbering and table choice.

:mod:`services.report` writes the report body as plain HTML — a preamble (the
project block), then chapters opened by ``<h2>`` and subsections opened by
``<h3>``. This module reads that structure back, so any section a report
builder adds with those two headings is listed, numbered and selectable without
registering it anywhere:

- :func:`report_outline` lists the chapters and subsections with a stable key
  each (the slug of the heading, ``chapter/subsection`` for a subsection);
- :func:`compose_report` leaves out the keys in :attr:`ReportOptions.excluded`,
  numbers the headings, turns the preamble into a cover page and writes the
  table of contents.

A paged page (for the PDF) carries a page-number placeholder per contents row
(:func:`page_placeholder`), which the PDF writer fills once it has laid the
pages out; it also draws the running header and footer
(:class:`RunningText`). No Qt here.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

_HEADING = re.compile(r"<h([23])(\s[^>]*)?>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_TABLE = re.compile(r"<table[\s>]", re.IGNORECASE)


@dataclass(frozen=True)
class ReportOptions:
    """What goes into the report and how it is laid out."""

    cover: bool = True
    """The project block on a page of its own."""
    cover_figure: bool = True
    """An isometric (3D) or elevation (2D) drawing of the structure on the cover."""
    contents: bool = True
    """A table of contents after the cover (with page numbers in the PDF)."""
    number_headings: bool = True
    """Chapters numbered 1, 2, … and their subsections 1.1, 1.2, …"""
    chapter_page_break: bool = False
    """Every chapter starts on a new page."""
    header_footer: bool = True
    """PDF: the project, the page number and the date on every page but the cover."""
    keep_tables_together: bool = True
    """PDF: a table that fits on one page is moved to the next one rather than cut."""
    language: str = "en"
    """"en" or "es" (:mod:`services.report_i18n`)."""
    excluded: frozenset[str] = field(default_factory=frozenset)
    """Keys (:attr:`ReportSection.key`) of the chapters and subsections left out."""


@dataclass(frozen=True)
class ReportSection:
    """One chapter (``level`` 2) or subsection (``level`` 3) of the report."""

    key: str
    title: str
    level: int
    parent: str | None
    tables: int
    """How many tables the section holds (not counting its subsections)."""


@dataclass(frozen=True)
class RunningText:
    """The header and footer the PDF writer draws on every page after the cover."""

    header_left: str
    header_right: str
    footer_left: str
    skip_first_page: bool = True
    page_format: str = "Page {page} of {pages}"


@dataclass
class _Chunk:
    level: int
    attrs: str
    inner: str
    title: str
    key: str
    parent: str | None
    content: str


def heading_text(inner: str) -> str:
    """The plain text of a heading's HTML (tags dropped, entities decoded)."""
    return " ".join(html.unescape(_TAG.sub("", inner)).split())


def slug(text: str) -> str:
    """A key made of lowercase letters, digits and dashes ("Results — Dead" → "results-dead")."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "section"


def _split(body: str) -> tuple[str, list[_Chunk]]:
    """The preamble before the first chapter, then one chunk per ``<h2>``/``<h3>``."""
    matches = list(_HEADING.finditer(body))
    preamble_end = next((m.start() for m in matches if m.group(1) == "2"), len(body))
    preamble = body[:preamble_end]
    chunks: list[_Chunk] = []
    used: set[str] = set()
    chapter: str | None = None
    headings = [m for m in matches if m.start() >= preamble_end]
    for i, m in enumerate(headings):
        level = int(m.group(1))
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        title = heading_text(m.group(3))
        base = slug(title) if level == 2 or chapter is None else f"{chapter}/{slug(title)}"
        key, n = base, 2
        while key in used:
            key, n = f"{base}-{n}", n + 1
        used.add(key)
        if level == 2:
            chapter = key
        chunks.append(
            _Chunk(
                level=level,
                attrs=m.group(2) or "",
                inner=m.group(3),
                title=title,
                key=key,
                parent=None if level == 2 else chapter,
                content=body[m.end() : end],
            )
        )
    return preamble, chunks


def report_outline(body: str) -> list[ReportSection]:
    """Every chapter and subsection of a report body, in reading order."""
    _preamble, chunks = _split(body)
    return [
        ReportSection(
            key=c.key,
            title=c.title,
            level=c.level,
            parent=c.parent,
            tables=len(_TABLE.findall(c.content)),
        )
        for c in chunks
    ]


def page_placeholder(anchor: str) -> str:
    """The text a paged contents row carries until the PDF writer knows the page."""
    return f"@@{anchor}@@"


_BREAK = ' style="page-break-before: always"'

PLACEHOLDER = re.compile(r"@@(s[0-9]+)@@")
"""Matches :func:`page_placeholder` text; group 1 is the heading's anchor name."""

LAYOUT_STYLE = """
p.cover-space { font-size: 60pt; margin: 0; }
p.cover-figure { text-align: center; margin: 6pt 0 18pt 0; }
h1.cover-title { font-size: 26pt; margin-bottom: 4pt; }
p.cover-kind { font-size: 14pt; color: #444; margin-bottom: 30pt; }
div.cover td, div.cover th { font-size: 10pt; padding: 3px 8px; }
h2.contents-title { border-bottom: 1px solid #888; }
table.contents { border-collapse: collapse; width: 100%; }
table.contents td { border: none; padding: 2px 4px; font-size: 10pt; white-space: normal;
                    text-align: left; }
table.contents td.sub { padding-left: 24px; font-size: 9pt; }
table.contents td.page { text-align: right; width: 40px; }
a { color: #111; text-decoration: none; }
@media print {
  table { page-break-inside: avoid; }
  thead { display: table-header-group; }
  h2, h3 { page-break-after: avoid; }
}
"""
"""Style the composed page adds to the body's own; page breaks are inline (Qt reads those)."""


def compose_report(
    body: str,
    *,
    title: str,
    style: str,
    options: ReportOptions | None = None,
    paged: bool = False,
    kind: str = "",
    cover_figure: str = "",
    contents_title: str = "",
) -> str:
    """The whole page: cover, contents, then the chapters ``options`` keeps.

    ``body`` is the report's HTML inside ``<body>``: a preamble (the project
    block, which becomes the cover), then chapters and subsections. ``paged``
    writes page-number placeholders in the contents (the PDF writer fills
    them); otherwise the contents rows link to the headings. ``cover_figure``
    is HTML (an ``<img>``) placed on the cover under the title.
    """
    from opensees_studio.services.report_i18n import translate_html

    options = options or ReportOptions()
    kind = kind or "Calculation report"
    contents_title = contents_title or "Contents"
    preamble, chunks = _split(body)
    excluded = options.excluded
    kept = [
        c
        for c in chunks
        if c.key not in excluded and (c.parent is None or c.parent not in excluded)
    ]
    rows: list[str] = []
    out: list[str] = []
    chapter = sub = 0
    for n, c in enumerate(kept):
        anchor = f"s{n + 1}"
        if c.level == 2:
            chapter, sub = chapter + 1, 0
            number = f"{chapter}"
        else:
            sub += 1
            number = f"{chapter}.{sub}" if chapter else f"{sub}"
        label = f"{number}&nbsp;&nbsp;{c.inner}" if options.number_headings else c.inner
        attrs = c.attrs
        first_after_front = n == 0 and (options.cover or (options.contents and bool(kept)))
        if first_after_front or (c.level == 2 and options.chapter_page_break):
            attrs += _BREAK
        out.append(f'<h{c.level}{attrs}><a name="{anchor}">{label}</a></h{c.level}>{c.content}')
        cls = "" if c.level == 2 else ' class="sub"'
        text = (
            f"{number}&nbsp;&nbsp;{html.escape(c.title)}"
            if options.number_headings
            else (html.escape(c.title))
        )
        if paged:
            rows.append(
                f'<tr><td{cls}>{text}</td><td class="page">{page_placeholder(anchor)}</td></tr>'
            )
        else:
            rows.append(f'<tr><td{cls}><a href="#{anchor}">{text}</a></td></tr>')
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>{style}{LAYOUT_STYLE}</style></head><body>",
    ]
    if options.cover:
        cover = re.sub(
            r"<h1(\s[^>]*)?>",
            '<p class="cover-space">&nbsp;</p><h1 class="cover-title">',
            preamble,
            count=1,
        )
        cover = cover.replace(
            "</h1>", f'</h1><p class="cover-kind">{html.escape(kind)}</p>{cover_figure}', 1
        )
        parts.append(f'<div class="cover">{cover}</div>')
    else:
        parts.append(preamble)
    if options.contents and rows:
        parts.append(
            f'<div class="contents"><h2 class="contents-title"{_BREAK if options.cover else ""}>'
            f'{html.escape(contents_title)}</h2><table class="contents" width="100%">{"".join(rows)}</table></div>'
        )
    if not kept and chunks:
        parts.append("<p>Every section is left out of this report.</p>")
    parts += out
    parts.append("</body></html>")
    # Keys and anchors come from the English headings, so a choice holds in every language.
    return translate_html("".join(parts), options.language)
