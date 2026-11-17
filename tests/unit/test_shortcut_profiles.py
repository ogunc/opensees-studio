"""Options → Keyboard Shortcuts: the SAP2000 profile moves only its own keys."""

from __future__ import annotations

from opensees_studio.core.shortcut_profiles import DEFAULT, SAP2000, profile_shortcuts

DEFAULTS = {
    "_act_run": ("F5",),
    "_act_check_model": ("F6",),
    "_act_tool_measure": ("F7",),
    "_act_show_deformed": (),
    "_act_table_editing": ("Ctrl+T",),
    "_act_zoom_in": ("Ctrl++", "Ctrl+="),
}


def test_the_default_profile_keeps_every_key() -> None:
    assert profile_shortcuts(DEFAULTS, DEFAULT) == DEFAULTS
    assert profile_shortcuts(DEFAULTS, "from-a-newer-version") == DEFAULTS


def test_sap2000_takes_f6_and_f7_from_their_default_owners() -> None:
    keys = profile_shortcuts(DEFAULTS, SAP2000)
    assert keys["_act_run"] == ("F5",)
    assert keys["_act_show_deformed"] == ("F6",)
    assert keys["_act_show_force_diagram"] == ("F7",)
    assert keys["_act_table_editing"] == ("Ctrl+T",)
    assert keys["_act_check_model"] == ()
    assert keys["_act_tool_measure"] == ()
    assert keys["_act_zoom_in"] == ("Ctrl++", "Ctrl+=")
    every = [key for value in keys.values() for key in value]
    assert len(every) == len(set(every)), "no key is shared"
