"""Interface translations: the English text of a widget to another language.

The catalog ``data/i18n/<language>.json`` maps English labels to their
translation. Labels are matched without their decorations: the keyboard
accelerator ``&``, a trailing ``…``, ``.`` or ``:`` (added back to the result),
and a trailing unit in brackets (``Thickness h [m]:`` translates ``Thickness h``
and keeps `` [m]:``). A text the catalog does not know stays as it is.

No Qt.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

LANGUAGES: dict[str, str] = {"en": "English", "es": "Español"}

_DATA = Path(__file__).resolve().parents[1] / "data" / "i18n"
_UNIT = re.compile(r"^(?P<body>.*?)(?P<unit>\s*\[[^\[\]]*\])?(?P<tail>[:…]*|\.\.\.)$", re.S)


@cache
def catalog(language: str) -> dict[str, str]:
    """English text → translation; empty for English or an unknown language."""
    path = _DATA / f"{language}.json"
    if language == "en" or not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def translate(text: str, language: str) -> str | None:
    """The translation of ``text``, decorations kept; ``None`` when unknown."""
    table = catalog(language)
    if not table or not text.strip():
        return None
    plain = text.replace("&&", "\x00").replace("&", "").replace("\x00", "&").strip()
    match = _UNIT.match(plain)
    if match is None:
        return None
    body, unit, tail = match.group("body").strip(), match.group("unit") or "", match.group("tail")
    found = table.get(body)
    if found is None and body.endswith("."):
        found = table.get(body.rstrip("."))
    if found is None:
        return None
    return f"{found}{unit}{tail}"
