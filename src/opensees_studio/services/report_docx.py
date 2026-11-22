"""The report as a Word document (.docx), written from the report page (no extra dependency).

:func:`docx_bytes` reads the page :func:`services.report.build_report` composed
(its cover, contents, chapters and tables) and writes WordprocessingML:

- the cover on its own page, without header and footer (a different first page);
- the contents as a Word table-of-contents field over the heading styles, which
  Word fills in with page numbers when it opens the file (it asks to update the
  fields);
- chapters as *Heading 1*, subsections as *Heading 2*, kept with what follows;
- tables with a repeated header row, rows that do not split, and — when
  ``keep_tables_together`` — every row kept with the next, so Word moves a table
  that fits on a page to the next page rather than cut it;
- the header (project, company) and the footer (program, date, "Page N of M"
  as PAGE and NUMPAGES fields);
- the cover drawing as a PNG, which the caller rasterises (``rasterize``), since
  this layer has no Qt.

No Qt here.
"""

from __future__ import annotations

import base64
import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.sax.saxutils import escape

from opensees_studio.services.report_layout import RunningText

_VOID = {"img", "br", "meta", "hr", "link", "col"}
_EMU_PER_PX = 9525
_PAGE_W, _PAGE_H = 11906, 16838  # A4 in twentieths of a point
_MARGIN = 851  # 15 mm
_TEXT_W = _PAGE_W - 2 * _MARGIN


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def find(self, tag: str) -> list[_Node]:
        out: list[_Node] = []
        for c in self.children:
            if isinstance(c, _Node):
                if c.tag == tag:
                    out.append(c)
                out += c.find(tag)
        return out


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self._stack[-1].tag not in ("style", "title", "head"):
            self._stack[-1].children.append(data)


def _parse(page: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(page)
    builder.close()
    bodies = builder.root.find("body")
    return bodies[0] if bodies else builder.root


def _run(text: str, *, bold: bool = False, italic: bool = False, size: float | None = None,
         color: str | None = None) -> str:  # fmt: skip
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{round(size * 2)}"/><w:szCs w:val="{round(size * 2)}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _para(
    runs: str,
    *,
    style: str | None = None,
    align: str | None = None,
    page_break_before: bool = False,
    keep_next: bool = False,
    spacing_before: int | None = None,
    spacing_after: int | None = None,
) -> str:
    props = []
    if style:
        props.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        props.append("<w:keepNext/>")
    if page_break_before:
        props.append("<w:pageBreakBefore/>")
    if spacing_before is not None or spacing_after is not None:
        attrs = ""
        if spacing_before is not None:
            attrs += f' w:before="{spacing_before}"'
        if spacing_after is not None:
            attrs += f' w:after="{spacing_after}"'
        props.append(f"<w:spacing{attrs}/>")
    if align:
        props.append(f'<w:jc w:val="{align}"/>')
    ppr = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
    return f"<w:p>{ppr}{runs}</w:p>"


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split()) if text.strip() else ""


def _heading_text(node: _Node) -> str:
    return " ".join(node.text().replace("\xa0\xa0", "  ").replace("\xa0", " ").split(" "))


def _field(instruction: str, placeholder: str = "") -> str:
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {escape(instruction)} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{_run(placeholder) if placeholder else ''}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


class _Writer:
    def __init__(
        self,
        rasterize: Callable[[bytes], tuple[bytes, int, int] | None] | None,
        keep_tables_together: bool,
        toc_hint: str,
    ) -> None:
        self.toc_hint = toc_hint
        self.body: list[str] = []
        self.media: dict[str, bytes] = {}
        self.rasterize = rasterize
        self.keep = keep_tables_together
        self._break_next = False

    def _take_break(self, forced: bool = False) -> bool:
        out = self._break_next or forced
        self._break_next = False
        return out

    def image(self, node: _Node) -> None:
        src = node.attrs.get("src", "")
        if self.rasterize is None or not src.startswith("data:image/svg+xml;base64,"):
            return
        result = self.rasterize(base64.b64decode(src.split(",", 1)[1]))
        if result is None:
            return
        png, _w, _h = result
        width = int(node.attrs.get("width", "0") or 0) or 520
        height = int(node.attrs.get("height", "0") or 0) or 340
        n = len(self.media) + 1
        self.media[f"image{n}.png"] = png
        rid = f"rIdImg{n}"
        cx, cy = width * _EMU_PER_PX, height * _EMU_PER_PX
        drawing = (
            "<w:r><w:drawing>"
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{n}" name="Picture {n}" descr="{escape(node.attrs.get("alt", ""))}"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{n}" name="image{n}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            "</pic:blipFill>"
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        )
        self.body.append(_para(drawing, align="center", spacing_after=240))

    def table(self, node: _Node) -> None:
        rows: list[tuple[bool, _Node]] = []
        for child in node.children:
            if not isinstance(child, _Node):
                continue
            if child.tag == "thead":
                rows += [(True, r) for r in child.find("tr")]
            elif child.tag == "tbody":
                rows += [(False, r) for r in child.find("tr")]
            elif child.tag == "tr":
                rows.append((False, child))
        if not rows:
            return
        cells = [
            [c for c in r.children if isinstance(c, _Node) and c.tag in ("td", "th")]
            for _h, r in rows
        ]
        columns = max((len(r) for r in cells), default=1) or 1
        widths = [500] * columns
        for (header, _r), row_cells in zip(rows, cells, strict=True):
            for c, cell in enumerate(row_cells):
                chars = len(_clean(cell.text())) * (1.1 if header else 1.0)
                widths[c] = max(widths[c], int(chars * 95) + 180)
        total = sum(widths)
        if total > _TEXT_W:
            widths = [int(w * _TEXT_W / total) for w in widths]
        grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
        out = [
            '<w:tbl><w:tblPr><w:tblStyle w:val="ReportTable"/>'
            f'<w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
            f'<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
        ]
        for i, (header, _row) in enumerate(rows):
            last = i == len(rows) - 1
            trpr = "<w:cantSplit/>" + ("<w:tblHeader/>" if header else "")
            out.append(f"<w:tr><w:trPr>{trpr}</w:trPr>")
            for c, cell in enumerate(cells[i]):
                text = _clean(cell.text())
                left = "text" in cell.classes() or header
                shade = '<w:shd w:val="clear" w:color="auto" w:fill="E8E8E8"/>' if header else ""
                out.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{widths[c]}" w:type="dxa"/>{shade}</w:tcPr>'
                    + _para(
                        _run(text, bold=header, size=8),
                        style="TableText",
                        align="left" if left else "right",
                        keep_next=self.keep and not last,
                    )
                    + "</w:tc>"
                )
            out.append("</w:tr>")
        out.append("</w:tbl>")
        self.body.append("".join(out))
        self.body.append(_para("", style="TableGap"))

    def block(self, node: _Node) -> None:
        tag = node.tag
        style = node.attrs.get("style", "").replace(" ", "")
        page_break = "page-break-before:always" in style
        if tag == "div" and "cover" in node.classes():
            for child in node.children:
                if isinstance(child, _Node):
                    self.block(child)
            self._break_next = True
            return
        if tag == "div" and "contents" in node.classes():
            heads = node.find("h2")
            title = _clean(heads[0].text()) if heads else "Contents"
            breaks = self._take_break(
                bool(heads) and "page-break-before" in heads[0].attrs.get("style", "")
            )
            self.body.append(_para(_run(title), style="TOCHeading", page_break_before=breaks))
            self.body.append(_para(_field('TOC \\o "1-2" \\h \\z \\u', self.toc_hint)))
            self._break_next = True
            return
        if tag in ("div", "body", "root"):
            for child in node.children:
                if isinstance(child, _Node):
                    self.block(child)
            return
        if tag == "h1":
            self.body.append(
                _para(
                    _run(_clean(node.text())), style="Title", page_break_before=self._take_break()
                )
            )
        elif tag in ("h2", "h3"):
            self.body.append(
                _para(
                    _run(_heading_text(node).strip()),
                    style="Heading1" if tag == "h2" else "Heading2",
                    page_break_before=self._take_break(page_break),
                )
            )
        elif tag == "table":
            if self._break_next:
                self.body.append(_para("", page_break_before=self._take_break()))
            self.table(node)
        elif tag == "p":
            classes = node.classes()
            images = node.find("img")
            if "cover-space" in classes:
                self.body.append(_para("", spacing_before=2400))
            elif images:
                for img in images:
                    self.image(img)
            elif "cover-kind" in classes:
                self.body.append(_para(_run(_clean(node.text())), style="Subtitle"))
            else:
                note = "note" in classes
                text = _clean(node.text())
                if text:
                    self.body.append(
                        _para(
                            _run(text, italic=note, color="555555" if note else None),
                            page_break_before=self._take_break(),
                        )
                    )


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial" w:eastAsia="Arial"/>
<w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="{lang}"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:sz w:val="52"/><w:szCs w:val="52"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="360"/></w:pPr><w:rPr><w:color w:val="444444"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:keepLines/><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="888888"/></w:pBdr>
<w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TOCHeading"><w:name w:val="TOC Heading"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:pPr><w:spacing w:after="200"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:spacing w:after="40"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="TOC2"><w:name w:val="toc 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:spacing w:after="40"/><w:ind w:left="360"/></w:pPr><w:rPr><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TableGap"><w:name w:val="Table Gap"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="120"/></w:pPr><w:rPr><w:sz w:val="8"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/>
<w:pPr><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="444444"/></w:pBdr><w:tabs><w:tab w:val="right" w:pos="{text_w}"/></w:tabs><w:spacing w:after="0"/></w:pPr><w:rPr><w:color w:val="444444"/><w:sz w:val="15"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/>
<w:pPr><w:pBdr><w:top w:val="single" w:sz="4" w:space="1" w:color="444444"/></w:pBdr><w:tabs><w:tab w:val="right" w:pos="{text_w}"/></w:tabs><w:spacing w:after="0"/></w:pPr><w:rPr><w:color w:val="444444"/><w:sz w:val="15"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="ReportTable"><w:name w:val="Report Table"/><w:tblPr>
<w:tblBorders><w:top w:val="single" w:sz="4" w:color="999999"/><w:left w:val="single" w:sz="4" w:color="999999"/>
<w:bottom w:val="single" w:sz="4" w:color="999999"/><w:right w:val="single" w:sz="4" w:color="999999"/>
<w:insideH w:val="single" w:sz="4" w:color="999999"/><w:insideV w:val="single" w:sz="4" w:color="999999"/></w:tblBorders>
<w:tblCellMar><w:left w:w="60" w:type="dxa"/><w:right w:w="60" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)


def _page_runs(page_format: str) -> str:
    """ "Page {page} of {pages}" as runs with PAGE and NUMPAGES fields."""
    out: list[str] = []
    rest = page_format
    while rest:
        cut = min((i for i in (rest.find("{page}"), rest.find("{pages}")) if i >= 0), default=-1)
        if cut < 0:
            out.append(_run(rest))
            break
        if cut:
            out.append(_run(rest[:cut]))
        if rest.startswith("{pages}", cut):
            out.append(_field("NUMPAGES", "1"))
            rest = rest[cut + len("{pages}") :]
        else:
            out.append(_field("PAGE", "1"))
            rest = rest[cut + len("{page}") :]
    return "".join(out)


def docx_bytes(
    page: str,
    *,
    running: RunningText | None = None,
    keep_tables_together: bool = True,
    rasterize: Callable[[bytes], tuple[bytes, int, int] | None] | None = None,
    language: str = "en",
    title: str = "",
) -> bytes:
    """The composed report ``page`` (HTML, not paged) as a .docx package.

    ``rasterize`` turns the cover's SVG drawing into ``(png, width, height)``;
    without it the drawing is left out.
    """
    hint = (
        "Actualizá el campo (F9) para ver el índice."
        if language == "es"
        else "Update the field (F9) to list the contents."
    )
    writer = _Writer(rasterize, keep_tables_together, hint)
    writer.block(_parse(page))
    rels = [
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
        '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',
    ]
    rels += [
        f'<Relationship Id="rIdImg{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image{n}.png"/>'
        for n in range(1, len(writer.media) + 1)
    ]
    sect_refs = ""
    parts: dict[str, str] = {}
    if running is not None:
        rels += [
            '<Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>',
            '<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>',
            '<Relationship Id="rIdHeaderFirst" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header2.xml"/>',
            '<Relationship Id="rIdFooterFirst" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer2.xml"/>',
        ]
        sect_refs = (
            '<w:headerReference w:type="default" r:id="rIdHeader"/>'
            '<w:footerReference w:type="default" r:id="rIdFooter"/>'
        )
        if running.skip_first_page:
            sect_refs += (
                '<w:headerReference w:type="first" r:id="rIdHeaderFirst"/>'
                '<w:footerReference w:type="first" r:id="rIdFooterFirst"/><w:titlePg/>'
            )
        tab = "<w:r><w:tab/></w:r>"
        parts["word/header1.xml"] = (
            f"<w:hdr {_NS}>"
            + _para(_run(running.header_left) + tab + _run(running.header_right), style="Header")
            + "</w:hdr>"
        )
        parts["word/footer1.xml"] = (
            f"<w:ftr {_NS}>"
            + _para(
                _run(running.footer_left) + tab + _page_runs(running.page_format), style="Footer"
            )
            + "</w:ftr>"
        )
        parts["word/header2.xml"] = f"<w:hdr {_NS}><w:p/></w:hdr>"
        parts["word/footer2.xml"] = f"<w:ftr {_NS}><w:p/></w:ftr>"
    sect = (
        f"<w:sectPr>{sect_refs}"
        f'<w:pgSz w:w="{_PAGE_W}" w:h="{_PAGE_H}"/>'
        f'<w:pgMar w:top="1247" w:right="{_MARGIN}" w:bottom="1247" w:left="{_MARGIN}" '
        'w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {_NS}><w:body>{''.join(writer.body)}{sect}</w:body></w:document>"
    )
    lang = "es-ES" if language == "es" else "en-US"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        + "".join(
            f'<Override PartName="/word/{name}{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{name}+xml"/>'
            for name in ("header", "footer")
            for n in (1, 2)
            if running is not None
        )
        + "</Types>"
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{escape(title)}</dc:title><dc:creator>OpenSees Studio</dc:creator>"
        "</cp:coreProperties>"
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:updateFields w:val="true"/></w:settings>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", package_rels)
        package.writestr("docProps/core.xml", core)
        package.writestr("word/document.xml", document)
        package.writestr(
            "word/styles.xml", _STYLES.replace("{lang}", lang).replace("{text_w}", str(_TEXT_W))
        )
        package.writestr("word/settings.xml", settings)
        package.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels)
            + "</Relationships>",
        )
        for name, xml in parts.items():
            package.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml)
        for name, data in writer.media.items():
            package.writestr(f"word/media/{name}", data)
    return buffer.getvalue()
