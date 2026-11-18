"""The interface catalog: decorations kept, unknown texts left alone."""

from __future__ import annotations

from opensees_studio.core.i18n import catalog, translate


def test_accelerators_ellipses_colons_and_units_are_kept_around_the_translation() -> None:
    assert translate("&File", "es") == "Archivo"
    assert translate("Save &As…", "es") == "Guardar como…"
    assert translate("Thickness h [m]:", "es") == "Espesor h [m]:"
    assert translate("Name:", "es") == "Nombre:"


def test_unknown_text_and_english_stay() -> None:
    assert translate("No such label", "es") is None
    assert translate("&File", "en") is None
    assert catalog("en") == {}


def test_the_catalog_has_no_empty_translation() -> None:
    assert all(value.strip() for value in catalog("es").values())
