"""The report as .docx: package parts, styles, the contents field, tables and the header."""

from __future__ import annotations

import io
import re
import zipfile

from opensees_studio.services.report_docx import docx_bytes
from opensees_studio.services.report_figure import svg_data_uri
from opensees_studio.services.report_layout import ReportOptions, RunningText, compose_report

BODY = (
    "<h1>Bridge</h1><p>Intro &amp; more</p>"
    '<p class="cover-figure"><img src="' + svg_data_uri("<svg/>") + '" width="100" height="50"></p>'
    "<h2>Model</h2><table><thead><tr><th>Item</th><th>Count</th></tr></thead>"
    '<tr><td class="text">Joints</td><td>4</td></tr><tr><td class="text">Elements</td><td>3</td></tr>'
    '</table><p class="note">A note.</p>'
    "<h2>Results — Dead</h2><h3>Peaks</h3><table><tr><td>1</td></tr></table>"
)


def _parts(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return {n: package.read(n).decode("utf-8", "replace") for n in package.namelist()}


def test_docx_package_and_body() -> None:
    page = compose_report(BODY, title="t", style="")
    running = RunningText("Bridge", "ACME", "OpenSees Studio", page_format="Page {page} of {pages}")
    calls: list[bytes] = []

    def rasterize(svg: bytes) -> tuple[bytes, int, int]:
        calls.append(svg)
        return b"\x89PNG fake", 100, 50

    parts = _parts(docx_bytes(page, running=running, rasterize=rasterize, title="Bridge"))
    assert {
        "[Content_Types].xml",
        "word/document.xml",
        "word/styles.xml",
        "word/settings.xml",
        "word/header1.xml",
        "word/footer1.xml",
        "word/media/image1.png",
    } <= set(parts)
    document = parts["word/document.xml"]
    assert calls == [b"<svg/>"]
    assert 'w:pStyle w:val="Title"' in document and ">Bridge<" in document
    assert 'TOC \\o "1-2"' in document
    assert document.count('w:val="Heading1"') == 2 and document.count('w:val="Heading2"') == 1
    assert ">1  Model<" in document and ">2.1  Peaks<" in document
    assert "<w:tblHeader/>" in document and "<w:cantSplit/>" in document
    assert "Intro &amp; more" in document and "<w:i/>" in document
    assert "<w:titlePg/>" in document
    footer = parts["word/footer1.xml"]
    assert "PAGE" in footer and "NUMPAGES" in footer and "Page " in footer and " of " in footer
    assert "ACME" in parts["word/header1.xml"]
    assert '<w:updateFields w:val="true"/>' in parts["word/settings.xml"]
    # Rows keep with the next one, except the last row of a table.
    model_table = re.search(r"<w:tbl>.*?</w:tbl>", document.split("Model", 1)[1]).group(0)
    assert model_table.count("<w:keepNext/>") == 2 * 2


def test_docx_without_header_drawing_or_keep() -> None:
    page = compose_report(BODY, title="t", style="", options=ReportOptions(cover=False))
    parts = _parts(docx_bytes(page, keep_tables_together=False, language="es"))
    document = parts["word/document.xml"]
    assert "word/header1.xml" not in parts and "<w:drawing>" not in document
    assert "<w:keepNext/>" not in document.split("<w:tbl>", 1)[1].split("</w:tbl>", 1)[0]
    assert 'w:val="es-ES"' in parts["word/styles.xml"]
