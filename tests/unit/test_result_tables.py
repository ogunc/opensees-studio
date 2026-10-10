"""Result tables: unit-named headers and a CSV that reads back the exact result values."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    Node,
    Project,
    TrussElement,
)
from opensees_studio.core.project import ProjectMeta
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.result_tables import (
    display_text,
    modal_tables,
    node_history_table,
    pushover_tables,
    response_spectrum_tables,
    static_tables,
    write_csv,
)
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.spectrum import ModeContribution

# Values a six-digit display cannot tell apart, and a few that need all 17 digits.
AWKWARD = [0.1 + 0.2, 1e-10, 1.0 / 3.0, -2.0322856141383964e-06, 123456789.01234567, 0.0]


def _project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        meta=ProjectMeta(units=UnitSystem.US_IN_KIP),
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))],
        materials=[ElasticUniaxial(id=1, E=29000.0)],
        sections=[ElasticSection(id=1, E=29000.0, A=1.0, Iz=1.0)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            TrussElement(id=2, nodes=(1, 2), area=1.0, material_id=1),
        ],
    )


def _static() -> StaticResults:
    rng = np.random.default_rng(7)
    return StaticResults(
        case_id=1,
        case_name="gravity",
        n_steps=2,
        node_disp={1: rng.normal(size=(2, 3)), 2: np.array([[0.0] * 3, AWKWARD[:3]])},
        node_reaction={1: np.array([[0.0] * 3, AWKWARD[3:]]), 2: rng.normal(size=(2, 3))},
        element_forces={1: rng.normal(size=(2, 6)), 2: rng.normal(size=(2, 6)) * 1e-9},
    )


def _read(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def test_static_headers_name_the_units() -> None:
    disp, reactions, forces = static_tables(_static(), _project())
    assert disp.columns == ["Node", "U1 [in]", "U2 [in]", "R3 [rad]"]
    assert reactions.columns == ["Node", "F1 [kip]", "F2 [kip]", "M3 [kip·in]"]
    assert forces.columns == ["Element", "Type", "Component", "Unit", "Value"]
    frame = [row for row in forces.rows if row[0] == 1]
    assert [(r[2], r[3]) for r in frame] == [
        ("N i", "kip"),
        ("V i", "kip"),
        ("M i", "kip·in"),
        ("N j", "kip"),
        ("V j", "kip"),
        ("M j", "kip·in"),
    ]
    truss = [row for row in forces.rows if row[0] == 2]
    assert truss[0][1] == "TrussElement"
    assert [r[2] for r in truss[:3]] == ["node 1 DOF 1", "node 1 DOF 2", "node 1 DOF 3"]
    assert [r[3] for r in truss[:3]] == ["kip", "kip", "kip·in"]


def test_static_csv_reads_back_the_result_object_exactly(tmp_path: Path) -> None:
    results = _static()
    disp, reactions, forces = static_tables(results, _project())

    header, rows = _read(write_csv(disp, tmp_path / "disp.csv"))
    assert header == disp.columns
    for row in rows:
        values = np.array([float(v) for v in row[1:]])
        assert np.array_equal(values, results.node_disp[int(row[0])][-1])

    _header, rows = _read(write_csv(reactions, tmp_path / "reactions.csv"))
    for row in rows:
        values = np.array([float(v) for v in row[1:]])
        assert np.array_equal(values, results.node_reaction[int(row[0])][-1])
    assert [float(v) for v in rows[0][1:]] == AWKWARD[3:]

    _header, rows = _read(write_csv(forces, tmp_path / "forces.csv"))
    for eid, recorded in results.element_forces.items():
        exported = [float(r[4]) for r in rows if int(r[0]) == eid]
        assert np.array_equal(exported, recorded[-1])


def test_display_rounds_and_export_does_not(tmp_path: Path) -> None:
    value = 0.1 + 0.2
    assert display_text(value, 6) == "0.3"
    assert display_text(value, 15) == "0.3"
    assert display_text(value, 17) == "0.30000000000000004"
    assert display_text(12, 3) == "12"
    disp = static_tables(_static(), _project())[0]
    text = write_csv(disp, tmp_path / "d.csv").read_text(encoding="utf-8")
    assert "0.30000000000000004" in text


def test_pushover_curve_and_modal_tables(tmp_path: Path) -> None:
    pushover = PushoverResults(
        case_id=3,
        case_name="push",
        n_steps=2,
        control_node=2,
        control_dof=1,
        control_disp=np.array([0.0, 0.1, 0.2 + 1e-17]),
        base_shear=np.array([0.0, AWKWARD[0], AWKWARD[2]]),
        node_disp={2: np.zeros((3, 3))},
    )
    curve = pushover_tables(pushover, _project())[0]
    assert curve.columns == ["Step", "Control U1 [in]", "Base shear [kip]"]
    _header, rows = _read(write_csv(curve, tmp_path / "curve.csv"))
    assert [float(r[2]) for r in rows] == list(pushover.base_shear)

    modal = ModalResults(case_id=4, case_name="modes", eigenvalues=np.array([AWKWARD[2], 4.0]))
    table = modal_tables(modal)[0]
    assert table.columns[1:] == ["Eigenvalue [rad²/s²]", "ω [rad/s]", "f [Hz]", "T [s]"]
    _header, rows = _read(write_csv(table, tmp_path / "modal.csv"))
    assert float(rows[0][1]) == AWKWARD[2]
    assert float(rows[1][4]) == float(modal.periods[1])


# ───────────────────── display-unit conversion ─────────────────────
# The project above is a US (in, kip) model. Showing it in SI multiplies every
# length by 0.0254, every force by 4448.2216152605 and every moment by both.
IN_M = 0.0254
KIP_N = 1000.0 * 4.4482216152605


def _shown_in_si() -> Project:
    project = _project()
    project.meta.display_units = UnitSystem.SI_M_N
    return project


def test_showing_a_us_model_in_si_converts_displacements_and_headers() -> None:
    results = _static()
    project = _shown_in_si()
    disp, reactions, forces = static_tables(results, project)

    assert disp.columns == ["Node", "U1 [m]", "U2 [m]", "R3 [rad]"]
    row = next(r for r in disp.rows if r[0] == 2)
    expected = np.asarray(results.node_disp[2][-1]) * np.array([IN_M, IN_M, 1.0])
    assert row[1:] == pytest.approx(list(expected))

    assert reactions.columns == ["Node", "F1 [N]", "F2 [N]", "M3 [N·m]"]
    row = next(r for r in reactions.rows if r[0] == 1)
    expected = np.asarray(results.node_reaction[1][-1]) * np.array([KIP_N, KIP_N, KIP_N * IN_M])
    assert row[1:] == pytest.approx(list(expected))

    # Element forces carry their unit per row, and the value follows it.
    frame = [r for r in forces.rows if r[0] == 1]
    assert [r[3] for r in frame] == ["N", "N", "N·m", "N", "N", "N·m"]
    recorded = np.asarray(results.element_forces[1][-1])
    factors = np.array([KIP_N, KIP_N, KIP_N * IN_M] * 2)
    assert [r[4] for r in frame] == pytest.approx(list(recorded * factors))
    # A rotation column is unit-free, so it must not move.
    assert disp.columns[3].endswith("[rad]")


def test_the_display_system_is_the_default_and_moves_nothing() -> None:
    """Without a display system the tables are exactly what they always were."""
    results = _static()
    disp, reactions, _forces = static_tables(results, _project())
    assert disp.rows[1][1:] == [float(v) for v in results.node_disp[2][-1]]
    assert reactions.rows[0][1:] == [float(v) for v in results.node_reaction[1][-1]]


def test_pushover_curve_converts_both_axes() -> None:
    pushover = PushoverResults(
        case_id=3,
        case_name="push",
        n_steps=1,
        control_node=2,
        control_dof=1,
        control_disp=np.array([0.0, 0.1, 0.2]),
        base_shear=np.array([0.0, 5.0, 10.0]),
        node_disp={2: np.zeros((3, 3))},
    )
    curve = pushover_tables(pushover, _shown_in_si())[0]
    assert curve.columns == ["Step", "Control U1 [m]", "Base shear [N]"]
    assert [r[1] for r in curve.rows] == pytest.approx([0.0, 0.1 * IN_M, 0.2 * IN_M])
    assert [r[2] for r in curve.rows] == pytest.approx([0.0, 5.0 * KIP_N, 10.0 * KIP_N])


def test_a_rotational_control_dof_stays_a_rotation() -> None:
    """A moment-curvature pushover drives R3: the rad column must not convert."""
    pushover = PushoverResults(
        case_id=3,
        case_name="push",
        n_steps=1,
        control_node=2,
        control_dof=3,
        control_disp=np.array([0.0, 1e-4]),
        base_shear=np.array([0.0, 7.0]),
        node_disp={2: np.zeros((2, 3))},
    )
    curve = pushover_tables(pushover, _shown_in_si())[0]
    assert curve.columns == ["Step", "Control R3 [rad]", "Base shear [N]"]
    assert curve.rows[1][1] == pytest.approx(1e-4)
    assert curve.rows[1][2] == pytest.approx(7.0 * KIP_N)


def test_node_history_converts_every_dof_of_the_selected_kind() -> None:
    history = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    results = TransientResults(
        case_id=5,
        case_name="quake",
        h5_path=Path("unused.h5"),
        n_steps=2,
        dt=0.01,
        n_steps_requested=2,
    )
    results.node_disp_history = lambda node_id: history  # type: ignore[method-assign]
    results.node_vel_history = lambda node_id: history  # type: ignore[method-assign]
    results.time = lambda: np.array([0.0, 0.01])  # type: ignore[method-assign]

    table = node_history_table(results, 1, "disp", _shown_in_si())
    # The project is 2D (ndf=3), so the third DOF is a rotation and stays in rad.
    assert table.columns == ["Time [s]", "U1 [m]", "U2 [m]", "R3 [rad]"]
    assert table.rows[1][1:] == pytest.approx([4.0 * IN_M, 5.0 * IN_M, 6.0])

    velocities = node_history_table(results, 1, "vel", _shown_in_si())
    assert velocities.columns == ["Time [s]", "V1 [m/s]", "V2 [m/s]", "VR3 [rad/s]"]
    # Time is a second in both systems, so it never converts.
    assert [r[0] for r in table.rows] == [0.0, 0.01]


def test_response_spectrum_converts_peak_displacements_and_sa() -> None:
    results = ResponseSpectrumResults(
        case_id=6,
        case_name="rs",
        direction=1,
        combination="CQC",
        combined_disp={1: np.array([0.01, 0.0, 0.0])},
        modes=[
            ModeContribution(
                mode_number=1,
                period=1.0,
                frequency=1.0,
                angular_frequency=2.0 * np.pi,
                participation_factor=1.2,
                effective_mass=3.0,
                mass_ratio=0.8,
                sa_at_period=0.5,
            )
        ],
    )
    combined, modes = response_spectrum_tables(results, _shown_in_si())
    assert combined.columns[1] == "U1 [m]"
    assert combined.rows[0][1] == pytest.approx(0.01 * IN_M)
    assert modes.columns[-1] == "Sa(T) [m/s²]"
    assert modes.rows[0][-1] == pytest.approx(0.5 * IN_M)


def test_headers_and_values_cannot_disagree() -> None:
    """Every converted cell is the raw cell times the factor its own header names."""
    results = _static()
    disp = static_tables(results, _shown_in_si())[0]
    factors = [IN_M, IN_M, 1.0]  # U1 [m], U2 [m], R3 [rad]
    for row in disp.rows:
        raw = results.node_disp[int(row[0])][-1]
        for value, recorded, factor in zip(row[1:], raw, factors, strict=True):
            assert value == pytest.approx(float(recorded) * factor)
