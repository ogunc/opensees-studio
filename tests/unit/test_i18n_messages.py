"""Every fixed message-box text in the interface has a Spanish translation.

A ``QMessageBox`` is a window, so the interface translator translates its title
and text when it shows, but only the texts the catalog knows. This reads the
source rather than running it: any literal title or text passed to
``QMessageBox.information/warning/critical/question`` must be in ``es.json``.
Texts built at run time (f-strings, ``str(exc)``) are out of its reach.
"""

from __future__ import annotations

import ast
from pathlib import Path

from opensees_studio.core.i18n import translate

VIEWS = Path(__file__).resolve().parents[2] / "src" / "opensees_studio" / "views"
_KINDS = {"information", "warning", "critical", "question"}


def _literal_texts() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(VIEWS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "QMessageBox"
                and func.attr in _KINDS
            ):
                continue
            for arg in node.args[1:3]:  # title, text
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((path.name, node.lineno, arg.value))
    return found


def test_the_scan_finds_the_message_boxes() -> None:
    assert len(_literal_texts()) > 100


def test_every_fixed_message_text_has_a_spanish_translation() -> None:
    missing = [
        f"{name}:{line}: {text!r}"
        for name, line, text in _literal_texts()
        if translate(text, "es") is None
    ]
    assert missing == []
