"""Options → Keyboard Shortcuts: the default keys or SAP2000's.

A profile only moves the keys it names. The SAP2000 profile gives F5 to Run,
F6 to Show Deformed Shape, F7 to Show Force Diagram and Ctrl+T to the tables,
as SAP2000 does; an action that held one of those keys by default (Check Model
on F6, Measure Distance on F7) keeps its menu entry and loses the key, because
Qt runs neither of two actions that share a key.

Pure: the window passes its actions' default keys by attribute name and sets
what :func:`profile_shortcuts` returns.
"""

from __future__ import annotations

from collections.abc import Mapping

DEFAULT = "default"
SAP2000 = "sap2000"

#: The profiles, in menu order, with their menu labels.
PROFILES: dict[str, str] = {DEFAULT: "Default", SAP2000: "SAP2000"}

#: Where the choice is kept (QSettings key).
SETTINGS_KEY = "shortcuts/profile"

#: The SAP2000 keys, by the window's action attribute.
SAP2000_KEYS: dict[str, str] = {
    "_act_run": "F5",
    "_act_show_deformed": "F6",
    "_act_show_force_diagram": "F7",
    "_act_table_editing": "Ctrl+T",
}

_OVERRIDES: dict[str, dict[str, str]] = {DEFAULT: {}, SAP2000: SAP2000_KEYS}


def profile_shortcuts(
    defaults: Mapping[str, tuple[str, ...]], profile: str
) -> dict[str, tuple[str, ...]]:
    """Every action's keys under ``profile``, from the default keys.

    An unknown profile is the default one, so a settings file from a newer
    version never leaves the window without keys.
    """
    overrides = _OVERRIDES.get(profile, {})
    taken = set(overrides.values())
    out: dict[str, tuple[str, ...]] = {}
    for name, keys in defaults.items():
        if name in overrides:
            out[name] = (overrides[name],)
        else:
            out[name] = tuple(key for key in keys if key not in taken)
    for name, key in overrides.items():
        out.setdefault(name, (key,))
    return out
