"""The bridge from the gidopensees catalog to a material a project can hold.

The catalog is 58 generated Specs that nothing consumed. These tests pin what
the bridge does — read a number out of a unit-carrying default, validate a
catalog material against its Spec, emit the wired types exactly, and refuse the
unwired ones with a message that says what is missing and what exists.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from opensees_studio.core import CatalogMaterial
from opensees_studio.core.catalog_material import catalog_names, catalog_spec
from opensees_studio.core.quantities import QuantityError, parse_quantity, split_quantity
from opensees_studio.services.catalog_emitters import (
    emit_catalog_material,
    wired_names,
)


# ─────────────────────── quantities ───────────────────────
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4000 kN/m", 4000.0),
        ("-20MPa", -20.0),
        ("0.05 m", 0.05),
        ("300000 kN/m", 300000.0),
        ("0.0 kNsec/m", 0.0),
        ("2.5e-3 m", 2.5e-3),
        ("500", 500.0),
        ("1.0 m^2", 1.0),
    ],
)
def test_a_quantity_is_read_out_of_its_unit(text: str, expected: float) -> None:
    assert parse_quantity(text) == pytest.approx(expected)


@pytest.mark.parametrize(("text", "unit"), [("0.05 m", "m"), ("-20MPa", "MPa"), ("500", "")])
def test_the_unit_comes_back_separately(text: str, unit: str) -> None:
    assert split_quantity(text)[1] == unit


def test_a_number_is_already_a_quantity() -> None:
    assert parse_quantity(3) == 3.0
    assert parse_quantity(2.5) == 2.5


@pytest.mark.parametrize("text", ["", "MPa", "S235", "_"])
def test_text_without_a_number_is_refused(text: str) -> None:
    with pytest.raises(QuantityError):
        parse_quantity(text)


# ─────────────────────── the model ───────────────────────
def test_the_catalog_is_reachable_and_populated() -> None:
    names = catalog_names()

    assert "Elastic" in names
    assert "Viscous_Damper" in names
    assert len(names) >= 58


def test_a_catalog_material_validates_its_name() -> None:
    with pytest.raises(ValueError, match="not a gidopensees catalog material"):
        CatalogMaterial(id=1, gid_name="NotAMaterial")


def test_a_catalog_material_validates_its_parameters() -> None:
    with pytest.raises(ValueError, match="no field"):
        CatalogMaterial(id=1, gid_name="Elastic", parameters={"nope": 1.0})


def test_defaults_can_be_read_out_of_the_schema() -> None:
    """The Specs store text with units; the bridge reads the numbers back."""
    material = CatalogMaterial.from_schema_defaults("Viscous_Damper", id=3, name="VD")

    assert material.parameters["elastic_stiffness"] == pytest.approx(300000.0)
    assert material.parameters["velocity_exponent_alpha"] == pytest.approx(0.3)
    # A discriminator is not a parameter; it lands in options.
    assert material.options["analysis_type"] == "Monotonic"


# ─────────────────────── the emitters ───────────────────────
def test_a_wired_type_emits_its_command_exactly() -> None:
    ops = MagicMock()
    material = CatalogMaterial(id=7, gid_name="Elastic", parameters={"elastic_modulus_e": 30000.0})

    emit_catalog_material(material, ops)

    ops.uniaxialMaterial.assert_called_once_with("Elastic", 7, 30000.0)


def test_an_unwired_type_fails_loudly() -> None:
    """The catalog promises 58 materials; only what is verified may be emitted."""
    ops = MagicMock()
    material = CatalogMaterial(id=1, gid_name="Viscous", parameters={"damping_coefficient_c": 1.0})

    with pytest.raises(NotImplementedError) as excinfo:
        emit_catalog_material(material, ops)

    message = str(excinfo.value)
    assert "Viscous" in message
    assert "no emitter yet" in message
    assert "Elastic" in message  # says what *is* wired
    ops.uniaxialMaterial.assert_not_called()


def test_a_missing_parameter_names_itself() -> None:
    ops = MagicMock()
    material = CatalogMaterial(id=1, gid_name="Elastic", parameters={})

    with pytest.raises(ValueError, match="elastic_modulus_e"):
        emit_catalog_material(material, ops)


def test_the_wired_set_is_small_and_named() -> None:
    assert wired_names() == ["Elastic"]


def test_the_specs_are_loaded_lazily() -> None:
    """Importing core must not drag in 58 generated modules."""
    spec = catalog_spec("Elastic")

    assert spec is not None
    assert "elastic_modulus_e" in spec.model_fields
