"""The numbers a shell contour paints: which node gets which value.

Pure data, no Qt and no VTK: the renderer's only job is to put these on faces,
so everything that could be wrong about a contour — the field it names, the
averaging at a shared node, the elements it leaves alone — is checked here.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    Project,
    ProjectMeta,
    ShellMITC4Element,
    UnitSystem,
)
from opensees_studio.services.results import StaticResults
from opensees_studio.services.shell_fields import (
    SHELL_FIELDS,
    displacement_scale,
    element_values,
    field_by_key,
    field_keys,
    nodal_values,
    shell_elements,
    warped_positions,
)


def _project() -> Project:
    """Two shells side by side sharing an edge, plus a bar that must be ignored."""
    return Project(
        meta=ProjectMeta(name="contour", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
            Node(id=3, coords=(1.0, 1.0, 0.0)),
            Node(id=4, coords=(0.0, 1.0, 0.0)),
            Node(id=5, coords=(2.0, 0.0, 0.0)),
            Node(id=6, coords=(2.0, 1.0, 0.0)),
        ],
        sections=[
            ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2, rho=0.0),
            ElasticSection(id=2, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6),
        ],
        elements=[
            ShellMITC4Element(id=20, nodes=(1, 2, 3, 4), section_id=1),
            ShellMITC4Element(id=21, nodes=(2, 5, 6, 3), section_id=1),
            ElasticBeamColumn(id=30, nodes=(1, 5), section_id=2),
        ],
    )


def _results() -> StaticResults:
    """N11 = 100 on element 20, 300 on element 21; a displacement field to match."""
    disp = {node_id: np.zeros((1, 6)) for node_id in (1, 2, 3, 4, 5, 6)}
    disp[1][0, 0] = 1e-3
    disp[2][0, 0] = 2e-3
    disp[3][0, 0] = 3e-3
    disp[4][0, 0] = 4e-3
    disp[5][0, 1] = 5e-3
    disp[6][0, 2] = -6e-3
    n11 = [100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    n21 = [300.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return StaticResults(
        case_id=1,
        case_name="contour",
        n_steps=1,
        node_disp=disp,
        element_stresses={20: np.array([n11]), 21: np.array([n21])},
    )


# ───────────────────────── the field registry ─────────────────────────
def test_the_registry_names_every_field_once() -> None:
    keys = field_keys()
    assert len(keys) == len(set(keys)) == len(SHELL_FIELDS)
    assert keys[:4] == ("umag", "ux", "uy", "uz")
    assert set(keys) >= {
        "N11",
        "N22",
        "N12",
        "M11",
        "M22",
        "M12",
        "V13",
        "V23",
        "N1",
        "N2",
        "M1",
        "M2",
        "V",
    }
    groups = {field.group for field in SHELL_FIELDS}
    assert groups == {"Deformation", "Membrane", "Bending", "Shear"}


def test_the_unit_label_follows_the_project_system() -> None:
    """A force per length reads N/m in SI and kip/in in kip-in units."""
    n11 = field_by_key("N11")
    m11 = field_by_key("M11")
    uz = field_by_key("uz")
    assert n11.unit_label(UnitSystem.SI_M_N) == "N/m"
    assert n11.unit_label(UnitSystem.US_IN_KIP) == "kip/in"
    assert m11.unit_label(UnitSystem.US_IN_KIP) == "kip·in/in"
    assert uz.unit_label(UnitSystem.SI_MM_N) == "mm"


def test_a_typo_fails_loudly() -> None:
    with pytest.raises(KeyError):
        field_by_key("N99")


def test_only_principal_fields_offer_a_direction() -> None:
    assert field_by_key("N1").direction is True
    assert field_by_key("M2").direction is True
    assert field_by_key("N11").direction is False
    assert field_by_key("uz").direction is False


# ───────────────────────── values per node and per element ─────────────────────────
def test_shell_elements_ignore_bars() -> None:
    elements = shell_elements(_project())
    assert [element.id for element in elements] == [20, 21]


def test_resultants_are_read_per_element() -> None:
    values = element_values(_project(), _results(), "N11")
    assert values == {20: pytest.approx(100.0), 21: pytest.approx(300.0)}
    # A bar has no resultants, so it is not in the map at all.
    assert 30 not in values


def test_a_principal_field_comes_from_the_element_row() -> None:
    """Element 21 is uniaxial, so N1 is its N11 and N2 is zero."""
    values = element_values(_project(), _results(), "N1")
    assert values[21] == pytest.approx(300.0)
    assert element_values(_project(), _results(), "N2")[21] == pytest.approx(0.0)


def test_a_shared_node_averages_the_elements_that_meet_there() -> None:
    """Node 2 belongs to both shells: (100 + 300) / 2, not one of them."""
    nodal = nodal_values(_project(), _results(), "N11")
    assert nodal[2] == pytest.approx(200.0)
    assert nodal[3] == pytest.approx(200.0)
    assert nodal[1] == pytest.approx(100.0)  # only element 20
    assert nodal[5] == pytest.approx(300.0)  # only element 21
    # A node no shell uses stays out of the map.
    assert set(nodal) == {1, 2, 3, 4, 5, 6}


def test_displacements_come_from_the_nodes() -> None:
    results = _results()
    project = _project()
    assert nodal_values(project, results, "ux")[3] == pytest.approx(3e-3)
    assert nodal_values(project, results, "uy")[5] == pytest.approx(5e-3)
    assert nodal_values(project, results, "uz")[6] == pytest.approx(-6e-3)
    assert nodal_values(project, results, "umag")[5] == pytest.approx(5e-3)
    assert nodal_values(project, results, "umag")[1] == pytest.approx(1e-3)


def test_an_element_field_of_a_displacement_is_the_mean_of_its_corners() -> None:
    values = element_values(_project(), _results(), "ux")
    assert values[20] == pytest.approx((1e-3 + 2e-3 + 3e-3 + 4e-3) / 4)
    assert values[21] == pytest.approx((2e-3 + 0.0 + 0.0 + 3e-3) / 4)


def test_a_model_without_resultants_paints_nothing() -> None:
    results = StaticResults(case_id=1, case_name="bars", n_steps=1, node_disp={1: np.zeros((1, 6))})
    assert element_values(_project(), results, "N11") == {}
    assert nodal_values(_project(), results, "N11") == {}


# ───────────────────────── warping ─────────────────────────
def test_the_scale_puts_the_peak_displacement_at_five_percent_of_the_model() -> None:
    project = _project()
    results = _results()
    scale = displacement_scale(project, results)
    peak = max(nodal_values(project, results, "umag").values())
    diagonal = float(
        np.linalg.norm(
            np.array([n.coords for n in project.nodes]).max(axis=0)
            - np.array([n.coords for n in project.nodes]).min(axis=0),
        ),
    )
    assert peak * scale == pytest.approx(0.05 * diagonal)


def test_no_displacement_means_no_scaling() -> None:
    results = StaticResults(case_id=1, case_name="zero", n_steps=1, node_disp={1: np.zeros((1, 6))})
    assert displacement_scale(_project(), results) == 1.0


def test_warping_adds_the_displacement_at_scale() -> None:
    project = _project()
    results = _results()
    positions = warped_positions(project, results, scale=10.0)
    assert positions[1] == pytest.approx((0.0 + 10 * 1e-3, 0.0, 0.0))
    assert positions[5] == pytest.approx((2.0, 10 * 5e-3, 0.0))
    assert positions[6] == pytest.approx((2.0, 1.0, 10 * -6e-3))
    # Scale zero is the undeformed model, exactly.
    assert warped_positions(project, results, scale=0.0)[3] == (1.0, 1.0, 0.0)
