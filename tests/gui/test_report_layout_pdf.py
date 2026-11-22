"""The report's PDF layout: tables kept off page breaks, contents page numbers, options dialog."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, QSizeF, Qt
from PySide6.QtGui import QTextDocument, QTextTable

from opensees_studio.services.report_layout import (
    PLACEHOLDER,
    ReportOptions,
    ReportSection,
    RunningText,
    compose_report,
)


def _body(chapters: int = 12, rows: int = 9) -> str:
    table = (
        "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
        + "".join(f"<tr><td>{i}</td><td>{i * i}</td></tr>" for i in range(rows))
        + "</table>"
    )
    return "<h1>Test</h1>" + "".join(
        f"<h2>Chapter {c}</h2><h3>Table {c}</h3><p>note</p>{table}" for c in range(chapters)
    )


def _document(page: str, height: float = 400.0) -> QTextDocument:
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setHtml(page)
    document.setPageSize(QSizeF(500.0, height))
    return document


def _tables(document: QTextDocument) -> list[QTextTable]:
    return [f for f in document.rootFrame().childFrames() if isinstance(f, QTextTable)]


@pytest.mark.gui
def test_tables_that_fit_on_a_page_are_not_cut(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.report_pdf import _keep_tables_together

    page = compose_report(_body(), title="t", style="", paged=True)
    height = 400.0

    def straddling(document: QTextDocument) -> int:
        layout = document.documentLayout()
        document.pageCount()
        out = 0
        for table in _tables(document)[1:]:  # past the contents
            rect = layout.frameBoundingRect(table)
            out += int(rect.top() // height) != int((rect.bottom() - 1) // height)
        return out

    assert straddling(_document(page, height)) > 0
    document = _document(page, height)
    assert _keep_tables_together(document, height) > 0
    assert straddling(document) == 0
    # The heading moved with its table.
    layout = document.documentLayout()
    for table in _tables(document)[1:]:
        block = document.findBlock(table.firstPosition() - 1).previous()
        assert block.blockFormat().headingLevel() == 3
        assert int(layout.blockBoundingRect(block).top() // height) == int(
            layout.frameBoundingRect(table).top() // height
        )


@pytest.mark.gui
def test_contents_get_the_page_of_each_heading(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.report_pdf import _anchor_pages, _fill_page_numbers

    document = _document(compose_report(_body(), title="t", style="", paged=True))
    _fill_page_numbers(document, 400.0)
    text = document.toPlainText()
    assert PLACEHOLDER.search(text) is None
    pages = _anchor_pages(document, 400.0)
    assert pages["s1"] >= 3  # cover, contents, then the chapters
    order = [pages[f"s{i}"] for i in range(1, len(pages) + 1)]
    assert order == sorted(order) and order[-1] <= document.pageCount()


@pytest.mark.gui
def test_write_pdf_with_header_and_footer(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.report_pdf import write_pdf

    page = compose_report(_body(30, 20), title="t", style="", paged=True)
    running = RunningText("Project", "Company", "OpenSees Studio")
    out = write_pdf(page, tmp_path / "r.pdf", running=running)
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page[^s]", data)) > 5
    plain = write_pdf(page, tmp_path / "p.pdf", keep_tables_together=False)
    assert plain.stat().st_size > 0


@pytest.mark.gui
def test_options_dialog_round_trip(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.report_options import (
        ReportOptionsDialog,
        load_options,
        save_options,
    )

    sections = [
        ReportSection("model", "Model", 2, None, 1),
        ReportSection("results-dead", "Results — Dead", 2, None, 0),
        ReportSection("results-dead/peaks", "Peaks", 3, "results-dead", 1),
    ]
    saved = ReportOptions(excluded=frozenset({"other-project-key"}))
    dialog = ReportOptionsDialog(sections, saved)
    qtbot.addWidget(dialog)
    child = dialog._items["results-dead/peaks"]
    dialog.set_checked("results-dead", False)
    assert child.isDisabled()
    dialog.set_checked("results-dead", True)
    assert not child.isDisabled()
    dialog.set_checked("results-dead/peaks", False)
    dialog._numbers.setChecked(False)
    options = dialog.options()
    assert options.excluded == {"other-project-key", "results-dead/peaks"}
    assert not options.number_headings and options.cover

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    assert load_options(settings) == ReportOptions()
    save_options(options, settings)
    assert load_options(settings) == options
    save_options(ReportOptions(excluded=frozenset({"one"})), settings)
    assert load_options(settings).excluded == {"one"}

    again = ReportOptionsDialog(sections, options)
    qtbot.addWidget(again)
    assert again._items["results-dead/peaks"].checkState(0) == Qt.CheckState.Unchecked
