"""Every fixed interface text in the views has a Spanish translation.

The interface translator (``views/i18n.py``) replaces a widget's text when the
catalog knows it, and :func:`views.i18n.tr` does the same for a text set at run
time. Both only work for texts in ``data/i18n/es.json``. This reads the source
rather than running it: a literal passed to a label, button, check box, group
box, window title, tab, form row, table header, placeholder or tool tip, and any
literal passed to ``tr``, must be in the catalog or in :data:`TECHNICAL` (symbols
and OpenSees parameter names that read the same in both languages).

Texts built at run time (f-strings) are out of its reach: write them as
``tr("... {n} ...").format(n=...)`` so the template is a literal it can check.
"""

from __future__ import annotations

import ast
from pathlib import Path

from opensees_studio.core.i18n import catalog, translate

VIEWS = Path(__file__).resolve().parents[2] / "src" / "opensees_studio" / "views"

#: Widgets whose first argument is the text they show.
_CONSTRUCTORS = {"QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QToolButton"}
#: Methods whose argument at this position is a text the user reads.
_METHODS = {
    "setText": 0,
    "setTitle": 0,
    "setWindowTitle": 0,
    "setPlaceholderText": 0,
    "setToolTip": 0,
    "addRow": 0,
    "addTab": 1,
    "tr": 0,
}
_LISTS = {"setHorizontalHeaderLabels", "setVerticalHeaderLabels", "setHeaderLabels"}

#: Symbols, units and OpenSees argument names: the same in English and Spanish.
TECHNICAL = {
    "#",
    "-iter:",
    "A:",
    "Agv:",
    "Ant:",
    "Anv:",
    "E0:",
    "E:",
    "Fexx:",
    "Fnv / Fnt:",
    "Fy:",
    "Fyf / Fyw:",
    "G:",
    "Hc",
    "Ie:",
    "Iy:",
    "Iz:",
    "J:",
    "Kinit:",
    "Lc",
    "Lw",
    "M_eff",
    "Qd:",
    "R:",
    "Reff:",
    "Rev",
    "S1 [g]:",
    "SD1 (g):",
    "SD1 [g]:",
    "SDS (g):",
    "Sa(T)",
    "Ss [g]:",
    "T (s)",
    "T1 [s]:",
    "TL (s):",
    "TL [s]:",
    "X, Y, Z:",
    "X:",
    "Y:",
    "Z:",
    "a",
    "aFast:",
    "aSlow:",
    "alpha0:",
    "alpha1 / alpha2 / mu:",
    "alpha1:",
    "alpha2:",
    "b",
    "bar_area:",
    "beta (Bouc-Wen):",
    "c",
    "dX:",
    "dY:",
    "dZ:",
    "dt [s]:",
    "dt:",
    "eta (Bouc-Wen):",
    "eta / beta / gamma:",
    "f (Hz)",
    "gamma (Bouc-Wen):",
    "maxMuFact:",
    "mu:",
    "muFast:",
    "muSlow:",
    "nFast:",
    "nSlow:",
    "n_bars:",
    "rect 0.3 0.5",
    "t",
    "x/L:",
    "y_end:",
    "y_start:",
    "z_end:",
    "z_start:",
    "α (1/°):",
    "Γ",
    "Δt (s):",
    "Δ2/Δ1",
    "ν (Poisson):",
    "…/site-packages",
    # Names the code also writes to the model or compares against.
    "CSYS1",
    "Global",
    "Ratio",
}


def _texts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _literal_texts() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(VIEWS.rglob("*.py")):
        if path.name == "i18n.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            texts: list[str] = []
            if name in _CONSTRUCTORS and node.args:
                texts = _texts(node.args[0])
            elif name in _METHODS and len(node.args) > _METHODS[name]:
                texts = _texts(node.args[_METHODS[name]])
            elif name in _LISTS and node.args and isinstance(node.args[0], ast.List | ast.Tuple):
                texts = [t for element in node.args[0].elts for t in _texts(element)]
            found += [(path.name, node.lineno, text) for text in texts]
    return found


def _needs_translation(text: str) -> bool:
    return any(c.isalpha() for c in text) and text not in TECHNICAL


def test_the_scan_finds_the_interface_texts() -> None:
    assert len(_literal_texts()) > 1500


def test_every_fixed_interface_text_has_a_spanish_translation() -> None:
    missing = sorted(
        {
            f"{name}:{line}: {text!r}"
            for name, line, text in _literal_texts()
            if _needs_translation(text) and translate(text, "es") is None
        }
    )
    assert missing == [], f"{len(missing)} texts without Spanish:\n" + "\n".join(missing)


def test_every_catalog_entry_can_be_found() -> None:
    """A key keeps no accelerator, trailing colon or ellipsis: the lookup strips them first."""

    def found(key: str, value: str) -> bool:
        # A key that ends in "…" is the label before its unit ("Bolts x,y; … [m]:").
        return translate(key, "es") == value or translate(f"{key} [m]", "es") == f"{value} [m]"

    unreachable = [key for key, value in catalog("es").items() if not found(key, value)]
    assert unreachable == []


def test_the_technical_list_holds_no_stale_entry() -> None:
    used = {text for _name, _line, text in _literal_texts()}
    assert used >= TECHNICAL, sorted(TECHNICAL - used)
