"""Unit tests for Phase 8a additions:

- UniformElementLoad schema round-trip
- PlainLoadPattern.element_loads persistence
- SetMassCommand undo/redo
- TransientCase Rayleigh fields defaults + round-trip
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.commands.nodes import SetMassCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    TransientCase,
    UniformElementLoad,
)
from opensees_studio.services import load_project, save_project


# ── fake viewmodel that SetMassCommand can work against ──────────────
class _FakeSignal:
    def __init__(self) -> None:
        self.emit_count = 0

    def emit(self) -> None:
        self.emit_count += 1


class _FakeVM:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.modelMutated = _FakeSignal()
        self.dirty_count = 0

    def mark_dirty(self) -> None:
        self.dirty_count += 1


@pytest.fixture
def tiny_project() -> Project:
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5, Iy=1e-5)],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
    )


# ── UniformElementLoad ───────────────────────────────────────────────
def test_uniform_element_load_schema() -> None:
    ld = UniformElementLoad(element_id=10, wy=-1000.0, wz=0.0, wx=0.0)
    assert ld.element_id == 10
    assert ld.wy == -1000.0
    assert ld.wz == 0.0


def test_plain_load_pattern_accepts_element_loads() -> None:
    pat = PlainLoadPattern(
        id=1, time_series_id=1,
        nodal_loads=[NodalLoad(node_id=1, forces=(0, 0, 0, 0, 0, 0))],
        element_loads=[UniformElementLoad(element_id=10, wy=-500.0)],
    )
    assert len(pat.element_loads) == 1
    assert pat.element_loads[0].wy == -500.0


def test_project_with_element_loads_round_trips(tiny_project: Project, tmp_path) -> None:  # type: ignore[no-untyped-def]
    tiny_project.time_series.append(LinearTimeSeries(id=1, name="Ramp"))
    tiny_project.load_patterns.append(PlainLoadPattern(
        id=1, time_series_id=1,
        element_loads=[UniformElementLoad(element_id=10, wy=-1500.0, wz=10.0)],
    ))

    path = tmp_path / "p.osmodel"
    save_project(tiny_project, path)
    restored = load_project(path)
    assert len(restored.load_patterns) == 1
    loads = restored.load_patterns[0].element_loads
    assert loads[0].element_id == 10
    assert loads[0].wy == -1500.0
    assert loads[0].wz == 10.0


# ── SetMassCommand ───────────────────────────────────────────────────
def test_set_mass_command_applies_and_undoes(tiny_project: Project) -> None:
    vm = _FakeVM(tiny_project)
    new_mass = (1000.0, 1000.0, 1000.0, 0.0, 0.0, 0.0)
    cmd = SetMassCommand(vm, {1, 2}, new_mass)

    cmd.redo()
    assert tiny_project.nodes[0].mass == new_mass
    assert tiny_project.nodes[1].mass == new_mass
    assert vm.modelMutated.emit_count == 1
    assert vm.dirty_count == 1

    cmd.undo()
    assert all(m == 0.0 for m in tiny_project.nodes[0].mass)
    assert all(m == 0.0 for m in tiny_project.nodes[1].mass)
    assert vm.modelMutated.emit_count == 2
    assert vm.dirty_count == 2


def test_set_mass_command_leaves_unselected_alone(tiny_project: Project) -> None:
    # Pre-set node 2's mass so we can prove it isn't touched.
    tiny_project.nodes[1] = tiny_project.nodes[1].model_copy(
        update={"mass": (5.0, 5.0, 5.0, 0.0, 0.0, 0.0)},
    )
    vm = _FakeVM(tiny_project)
    cmd = SetMassCommand(vm, {1}, (99.0, 0, 0, 0, 0, 0))

    cmd.redo()
    assert tiny_project.nodes[0].mass[0] == 99.0
    assert tiny_project.nodes[1].mass[0] == 5.0     # unchanged

    cmd.undo()
    assert tiny_project.nodes[0].mass[0] == 0.0


# ── TransientCase Rayleigh fields ────────────────────────────────────
def test_transient_case_rayleigh_defaults_to_zero() -> None:
    case = TransientCase(id=1, pattern_ids=[1], dt=0.01, n_steps=100)
    assert case.rayleigh_alpha_m == 0.0
    assert case.rayleigh_beta_k == 0.0


def test_transient_case_rayleigh_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
               Node(id=2, coords=(1, 0, 0))],
        sections=[ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5, Iy=1e-5)],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1)],
        analyses=[TransientCase(
            id=1, pattern_ids=[1], dt=0.01, n_steps=50,
            rayleigh_alpha_m=0.5, rayleigh_beta_k=1.5e-4,
        )],
    )
    path = tmp_path / "r.osmodel"
    save_project(p, path)
    restored = load_project(path)
    case = restored.analyses[0]
    assert case.rayleigh_alpha_m == 0.5
    assert case.rayleigh_beta_k == 1.5e-4


# ── Kinit-proportional (initial-stiffness) Rayleigh damping ───────────────────
def test_transient_case_rayleigh_init_comm_defaults() -> None:
    """The new initial/committed-K βK slots default to 0 (no behaviour change)."""
    case = TransientCase(id=1, pattern_ids=[1], dt=0.01, n_steps=10)
    assert case.rayleigh_beta_k_init == 0.0
    assert case.rayleigh_beta_k_comm == 0.0


def test_transient_case_rayleigh_init_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
               Node(id=2, coords=(1, 0, 0))],
        sections=[ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5, Iy=1e-5)],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1)],
        analyses=[TransientCase(
            id=1, pattern_ids=[1], dt=0.01, n_steps=50,
            rayleigh_beta_k_init=0.01309796,
        )],
    )
    path = tmp_path / "rk.osmodel"
    save_project(p, path)
    case = load_project(path).analyses[0]
    assert case.rayleigh_beta_k_init == pytest.approx(0.01309796)
    assert case.rayleigh_beta_k_comm == 0.0


def test_zero_length_do_rayleigh_default_and_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import ElasticUniaxial, ZeroLengthElement

    p = Project(
        ndm=3, ndf=6,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
               Node(id=2, coords=(0, 0, 0))],
        materials=[ElasticUniaxial(id=1, E=1000.0)],
        elements=[
            ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1,)),
            ZeroLengthElement(id=2, nodes=(1, 2), material_ids=(1,), dofs=(1,),
                              do_rayleigh=True),
        ],
    )
    assert p.elements[0].do_rayleigh is False  # default off (unchanged emission)
    assert p.elements[1].do_rayleigh is True
    path = tmp_path / "zl.osmodel"
    save_project(p, path)
    restored = load_project(path)
    assert restored.elements[0].do_rayleigh is False
    assert restored.elements[1].do_rayleigh is True


class _RecordingOps:
    """Records every ``ops.*`` call so a test can assert the emitted command
    sequence (the documented ``OpenSeesRunner(project, ops_module=...)`` hook)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        def rec(*args, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append((name, args, kwargs))
            return None
        return rec


def _transient_setup_rayleigh_calls(case: TransientCase) -> list[tuple]:
    from opensees_studio.services import OpenSeesRunner

    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
               Node(id=2, coords=(1, 0, 0), mass=(1.0,) * 3 + (0.0,) * 3)],
        sections=[ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5, Iy=1e-5)],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1)],
        analyses=[case],
    )
    rec = _RecordingOps()
    runner = OpenSeesRunner(p, ops_module=rec)
    runner._setup_analysis(case)
    return [c[1] for c in rec.calls if c[0] == "rayleigh"]


def test_kinit_rayleigh_issues_exactly_one_call_in_beta_kinit_slot() -> None:
    """A Kinit (initial-stiffness) βK is emitted ONCE as ``rayleigh 0 0 βKinit 0``
    — slot 3 — the single-command requirement (a second call would replace it)."""
    case = TransientCase(
        id=1, pattern_ids=[1], dt=0.01, n_steps=10,
        rayleigh_beta_k_init=0.01309796,
    )
    rcalls = _transient_setup_rayleigh_calls(case)
    assert len(rcalls) == 1
    assert rcalls[0] == (0.0, 0.0, pytest.approx(0.01309796), 0.0)


def test_current_k_rayleigh_unchanged_slot2() -> None:
    """The classical current-K βK still emits in slot 2 (backward compatible)."""
    case = TransientCase(
        id=1, pattern_ids=[1], dt=0.01, n_steps=10, rayleigh_beta_k=0.002,
    )
    rcalls = _transient_setup_rayleigh_calls(case)
    assert len(rcalls) == 1
    assert rcalls[0] == (0.0, pytest.approx(0.002), 0.0, 0.0)


def test_no_rayleigh_when_all_coefficients_zero() -> None:
    """No damping coefficients → no ``rayleigh`` command at all (unchanged)."""
    case = TransientCase(id=1, pattern_ids=[1], dt=0.01, n_steps=10)
    assert _transient_setup_rayleigh_calls(case) == []


def test_zero_length_do_rayleigh_emits_flag() -> None:
    """``do_rayleigh=True`` adds ``-doRayleigh 1`` to the zeroLength command; the
    default omits it (the original emission)."""
    from opensees_studio.core import ElasticUniaxial, ZeroLengthElement
    from opensees_studio.services import OpenSeesRunner

    p = Project(
        ndm=3, ndf=6,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
               Node(id=2, coords=(0, 0, 0))],
        materials=[ElasticUniaxial(id=1, E=1000.0)],
        elements=[
            ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1,)),
            ZeroLengthElement(id=2, nodes=(1, 2), material_ids=(1,), dofs=(1,),
                              do_rayleigh=True),
        ],
    )
    rec = _RecordingOps()
    OpenSeesRunner(p, ops_module=rec).build()
    zl = [c[1] for c in rec.calls if c[0] == "element" and c[1][0] == "zeroLength"]
    assert len(zl) == 2
    assert "-doRayleigh" not in zl[0]  # default off
    assert "-doRayleigh" in zl[1] and 1 in zl[1]  # opted in
