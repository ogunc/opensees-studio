"""Shell element and plate section: the models and the commands they emit.

The physics is verified against closed-form solutions in
``tests/integration/test_shell_plate.py``; this module pins the models and the
exact OpenSees command sequence, so a change in either is caught without a
solver run.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    ElasticMembranePlateSection,
    Node,
    Project,
    ShellMITC4Element,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner


def _project(**overrides: object) -> Project:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(1.0, 0.0, 0.0)),
        Node(id=3, coords=(1.0, 1.0, 0.0)),
        Node(id=4, coords=(0.0, 1.0, 0.0)),
    ]
    fields: dict[str, object] = {
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "sections": [ElasticMembranePlateSection(id=1, E=200e9, nu=0.3, h=0.2, rho=7850.0)],
        "elements": [ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)],
    }
    fields.update(overrides)
    return Project(**fields)  # type: ignore[arg-type]


# ─────────────────────── the models ───────────────────────
def test_a_plate_section_carries_its_own_elastic_properties() -> None:
    """A shell section is defined by E, nu, h, rho — it needs no nDMaterial."""
    section = ElasticMembranePlateSection(id=3, E=200e9, nu=0.3, h=0.25)

    assert section.type == "ElasticMembranePlateSection"
    assert (section.E, section.nu, section.h, section.rho) == (200e9, 0.3, 0.25, 0.0)


@pytest.mark.parametrize("nu", [-1.5, 0.6])
def test_an_impossible_poisson_ratio_is_refused(nu: float) -> None:
    with pytest.raises(ValidationError):
        ElasticMembranePlateSection(id=1, E=1.0, nu=nu, h=1.0)


def test_a_shell_needs_four_distinct_nodes() -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        ShellMITC4Element(id=1, nodes=(1, 2, 2, 4), section_id=1)

    element = ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)
    assert element.nodes == (1, 2, 3, 4)


def test_the_element_survives_a_project_round_trip() -> None:
    """It is part of the discriminated union, so it persists like any other."""
    project = _project()

    again = Project.model_validate(project.model_dump(mode="json", by_alias=True))

    element = again.elements[0]
    assert isinstance(element, ShellMITC4Element)
    assert element.section_id == 1
    assert isinstance(again.sections[0], ElasticMembranePlateSection)


# ─────────────────────── the commands ───────────────────────
def test_the_runner_emits_the_section_and_the_element() -> None:
    ops = MagicMock()

    OpenSeesRunner(_project(), ops_module=ops).build()

    ops.section.assert_called_once_with("ElasticMembranePlateSection", 1, 200e9, 0.3, 0.2, 7850.0)
    ops.element.assert_called_once_with("ShellMITC4", 1, 1, 2, 3, 4, 1)


def test_the_element_is_emitted_after_its_section() -> None:
    """OpenSees resolves the section tag when the element is created."""
    ops = MagicMock()

    OpenSeesRunner(_project(), ops_module=ops).build()

    names = [call[0] for call in ops.mock_calls]
    assert names.index("section") < names.index("element")


def test_a_shell_model_is_three_dimensional() -> None:
    ops = MagicMock()

    OpenSeesRunner(_project(), ops_module=ops).build()

    assert ops.model.call_args.args[:1] == ("basic",)
    assert "3" in [str(a) for a in ops.model.call_args.args]


def test_the_shell_and_the_plane_quad_are_different_elements() -> None:
    """A quad is a 2D plane element with a thickness; a shell is a 3D section."""
    from opensees_studio.core import QuadElement

    quad = QuadElement(id=1, nodes=(1, 2, 3, 4), thickness=0.2, material_id=1)

    assert quad.type == "Quad"
    assert ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1).type == "ShellMITC4"
