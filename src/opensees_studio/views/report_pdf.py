"""Print the report page to PDF with Qt's rich-text engine (no browser, no extra dependency).

The page is laid out on A4 by :class:`QTextDocument` and painted page by page,
so the writer can:

- keep a table that fits on one page off a page break, together with the
  heading and notes just above it (``keep_tables_together``);
- repeat a long table's header row on every page it runs over (``<thead>``);
- fill the contents' page numbers (:func:`services.report_layout.page_placeholder`);
- draw the running header and footer (:class:`services.report_layout.RunningText`)
  with "Page N of M".
"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QMarginsF,
    QPointF,
    QRectF,
    QRegularExpression,
    QSizeF,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
    QTextBlock,
    QTextBlockFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrame,
    QTextTable,
)
from PySide6.QtSvg import QSvgRenderer

from opensees_studio.services.report_layout import PLACEHOLDER, RunningText

_MARGIN_MM = 15.0
_RUNNING_MM = 22.0
"""Top and bottom margin when a header and footer are drawn in them."""
_LEAD_BLOCKS = 4
"""At most this many blocks (heading, notes) above a table move with it."""


class _ReportDocument(QTextDocument):
    """Draws the page's ``data:image/svg+xml`` images (the cover drawing) sharply."""

    def loadResource(self, kind: int, name: QUrl | str) -> object:
        text = name.toString() if isinstance(name, QUrl) else name
        if kind == QTextDocument.ResourceType.ImageResource.value and text.startswith(
            "data:image/svg+xml;base64,"
        ):
            image = _svg_image(base64.b64decode(text.split(",", 1)[1]))
            if image is not None:
                return image
        return super().loadResource(kind, name)


def _svg_image(svg: bytes, scale: float = 5.0) -> QImage | None:
    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        return None
    size = renderer.defaultSize()
    image = QImage(
        int(size.width() * scale), int(size.height() * scale), QImage.Format.Format_ARGB32
    )
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def svg_to_png(svg: bytes, scale: float = 4.0) -> tuple[bytes, int, int] | None:
    """``svg`` rasterised to PNG bytes, with its own size (for the Word report)."""
    image = _svg_image(svg, scale)
    if image is None:
        return None
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")  # type: ignore[call-overload]
    buffer.close()
    return bytes(data.data()), int(image.width() / scale), int(image.height() / scale)


def _mm(value: float, dpi: int) -> float:
    return value / 25.4 * dpi


def _page_of(top: float, page_height: float) -> int:
    return int(top // page_height)


def _lead(table: QTextTable) -> QTextBlock | None:
    """The heading a table belongs to: the nearest one above it, past only short notes."""
    document = table.document()
    block = document.findBlock(table.firstPosition() - 1)
    for _ in range(_LEAD_BLOCKS):
        if not block.isValid() or QTextCursor(block).currentTable() is not None:
            return None
        if block.blockFormat().headingLevel() > 0:
            above = block.previous()  # a chapter heading right above its first subsection
            while above.isValid() and above.blockFormat().headingLevel() > 0:
                block, above = above, above.previous()
            return block
        block = block.previous()
    return None


def _break_before(block: QTextBlock | None, table: QTextTable) -> None:
    if block is not None:
        fmt = QTextBlockFormat()
        fmt.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        QTextCursor(block).mergeBlockFormat(fmt)
    else:
        table_format = table.format()
        table_format.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        table.setFormat(table_format)


def _keep_tables_together(document: QTextDocument, page_height: float) -> int:
    """Move each table that fits on a page but straddles a break onto the next page.

    Returns how many tables were moved. A table taller than a page is left to
    run over the break (its header row repeats); its heading still moves when
    it would sit alone at the bottom of a page.
    """
    layout = document.documentLayout()
    moved = 0
    frames: list[QTextFrame] = list(document.rootFrame().childFrames())
    for frame in frames:
        if not isinstance(frame, QTextTable):
            continue
        document.pageCount()  # lays the document out up to date
        rect = layout.frameBoundingRect(frame)
        lead = _lead(frame)
        top = layout.blockBoundingRect(lead).top() if lead is not None else rect.top()
        first = _page_of(top, page_height)
        if top - first * page_height < 1.0:
            continue  # already starts a page
        if rect.height() <= page_height * 0.95:
            end = rect.bottom() - 1.0
        else:  # a long table: keep the heading with the first rows only
            end = min(rect.bottom(), rect.top() + page_height * 0.1)
        if _page_of(end, page_height) != first:
            _break_before(lead, frame)
            moved += 1
    return moved


def _anchor_pages(document: QTextDocument, page_height: float) -> dict[str, int]:
    """The 1-based page of every anchor (``<a name>``) in the document."""
    layout = document.documentLayout()
    pages: dict[str, int] = {}
    block = document.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            for name in fragment.charFormat().anchorNames():
                if name not in pages:
                    top = layout.blockBoundingRect(block).top()
                    pages[name] = _page_of(top, page_height) + 1
            it += 1
        block = block.next()
    return pages


def _fill_page_numbers(document: QTextDocument, page_height: float) -> None:
    pages = _anchor_pages(document, page_height)
    pattern = QRegularExpression(PLACEHOLDER.pattern)
    cursor = document.find(pattern)
    while not cursor.isNull():
        match = PLACEHOLDER.fullmatch(cursor.selectedText())
        page = pages.get(match.group(1)) if match else None
        cursor.insertText(str(page) if page is not None else "")
        cursor = document.find(pattern, cursor)


def _draw_running(
    painter: QPainter,
    running: RunningText,
    page: int,
    pages: int,
    *,
    width: float,
    height: float,
    dpi: int,
) -> None:
    left = _mm(_MARGIN_MM, dpi)
    right = width - left
    font = QFont("Arial")
    font.setPointSizeF(7.5)
    painter.setFont(font)
    painter.setPen(QPen(QColor("#444444"), _mm(0.2, dpi)))
    line_h = painter.fontMetrics().height()
    head_base = _mm(_RUNNING_MM - 7.0, dpi)
    foot_top = height - _mm(_RUNNING_MM - 7.0, dpi)
    align_l = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    align_r = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    span = right - left
    head = QRectF(left, head_base - line_h, span, line_h)
    painter.drawText(head, align_l, running.header_left)
    painter.drawText(head, align_r, running.header_right)
    painter.drawLine(
        QPointF(left, head_base + _mm(1, dpi)), QPointF(right, head_base + _mm(1, dpi))
    )
    painter.drawLine(QPointF(left, foot_top), QPointF(right, foot_top))
    foot = QRectF(left, foot_top + _mm(1, dpi), span, line_h)
    painter.drawText(foot, align_l, running.footer_left)
    painter.drawText(foot, align_r, running.page_format.format(page=page, pages=pages))


def write_pdf(
    page: str,
    path: str | Path,
    *,
    running: RunningText | None = None,
    keep_tables_together: bool = True,
) -> Path:
    """Lay ``page`` (HTML) out on A4 pages and write it to ``path``.

    ``running`` adds the header and footer; ``keep_tables_together`` moves a
    table that would be cut by a page break to the next page.
    """
    path = Path(path)
    writer = QPdfWriter(str(path))
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Unit.Millimeter,
        )
    )
    writer.setTitle(path.stem)
    writer.setCreator("OpenSees Studio")
    dpi = writer.resolution()
    width, height = float(writer.width()), float(writer.height())
    side = _mm(_MARGIN_MM, dpi)
    top = bottom = _mm(_RUNNING_MM if running is not None else _MARGIN_MM, dpi)
    body = QRectF(side, top, width - 2 * side, height - top - bottom)

    document = _ReportDocument()
    document.documentLayout().setPaintDevice(writer)
    document.setDocumentMargin(0)
    document.setHtml(page)
    document.setPageSize(QSizeF(body.width(), body.height()))
    page_height = body.height()
    if keep_tables_together:
        _keep_tables_together(document, page_height)
    _fill_page_numbers(document, page_height)

    pages = document.pageCount()
    painter = QPainter()
    if not painter.begin(writer):
        raise OSError(f"Could not write {path}.")
    try:
        for index in range(pages):
            if index:
                writer.newPage()
            painter.save()
            painter.translate(body.left(), body.top() - index * page_height)
            document.drawContents(
                painter, QRectF(0, index * page_height, body.width(), page_height)
            )
            painter.restore()
            if running is not None and not (running.skip_first_page and index == 0):
                _draw_running(
                    painter, running, index + 1, pages, width=width, height=height, dpi=dpi
                )
    finally:
        painter.end()
    if not path.exists():
        raise OSError(f"Could not write {path}.")
    return path
