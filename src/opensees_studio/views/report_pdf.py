"""Print the report page to PDF with Qt's rich-text engine (no browser, no extra dependency)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument


def write_pdf(page: str, path: str | Path) -> Path:
    """Lay ``page`` (HTML) out on A4 pages and write it to ``path``."""
    path = Path(path)
    writer = QPdfWriter(str(path))
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15),
            QPageLayout.Unit.Millimeter,
        )
    )
    writer.setTitle(path.stem)
    document = QTextDocument()
    document.setHtml(page)
    document.print_(writer)
    if not path.exists():
        raise OSError(f"Could not write {path}.")
    return path
