"""A wizard-built portal frame, solved: is it a structure or a mechanism?

Three checks, none of them against the application's own output:

- the default frame (gable roof, fixed bases, out-of-plane restraint) carries
  gravity without a singular stiffness matrix — the failure mode a plane frame
  in a 3D model has, and the reason the wizard restrains the out-of-plane DOF;
- a pinned-base frame with a far stiffer girder sways to ``H h^3 / (6 E I)``,
  which is the closed-form stiffness of two columns whose tops cannot rotate
  (slope-deflection, one end pinned and the other fixed against rotation:
  ``V = 3 EI Δ / h^3`` each);
- the response is linear in the load, which pins that the model that solved is
  the one being loaded.

Measured on this build (E = 200 GPa, I = 1e-5 m⁴, h = 4 m, H = 1 kN): the sway
is 5.335511e-3 m against 5.333333e-3 m from the closed form, +0.041 %, the
finite girder being very slightly more flexible than the rigid one the formula
assumes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    PortalFrameSpec,
    Project,
    RoofType,
    StaticCase,
    SupportCondition,
    build_portal_frame,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

E = 200e9
"""Elastic modulus, Pa."""
I_COL = 1e-5
"""Column second moment of area, m^4 (same about both local axes: the check must
not depend on how the local axes of a member along X land in the XZ plane)."""
A_MEMBER = 0.01
"""Member area, m^2."""
H = 4.0
"""Eave height, m."""
BAY = 6.0
"""Bay width, m."""
H_FORCE = 1000.0
"""Lateral force at the eave, N (split between the two columns)."""

SWAY_CLASSICAL = H_FORCE * H**3 / (6.0 * E * I_COL)
"""Δ = H h³ / (6 E I) for a pinned-base portal with a rigid girder."""


def _section(sid: int, *, name: str, i: float, area: float = A_MEMBER) -> ElasticSection:
    return ElasticSection(
        id=sid,
        name=name,
        E=E,
        A=area,
        Iz=i,
        Iy=i,
        G=80e9,
        J=1e-6,
    )


def _project(*, roof: RoofType, support: SupportCondition, rigid_girder: bool):
    """A one-bay frame, the wizard's default shape, plus whatever case is asked for."""
    spec = PortalFrameSpec(
        bay_width=BAY,
        eave_height=H,
        column_section_id=1,
        rafter_section_id=2,
        roof=roof,
        slope=0.0 if rigid_girder else 0.10,
        support=support,
        plane="XZ",
    )
    frame = build_portal_frame(spec, ndm=3, ndf=6, first_node_id=1, first_element_id=1)
    sections = [
        _section(1, name="Column", i=I_COL),
        _section(
            2,
            name="Rafter",
            i=I_COL * 1e4 if rigid_girder else I_COL,
            area=1.0 if rigid_girder else A_MEMBER,
        ),
    ]
    return Project(
        ndm=3,
        ndf=6,
        nodes=frame.nodes,
        sections=sections,
        elements=frame.elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[],
        analyses=[],
    ), frame


def _with_sway(project: Project, frame) -> Project:  # type: ignore[no-untyped-def]
    """Half the lateral force at each eave node — symmetric, so the frame sways."""
    loads = [
        NodalLoad(node_id=node_id, forces=(H_FORCE / 2.0, 0.0, 0.0, 0, 0, 0))
        for node_id in frame.top_node_ids
    ]
    project.load_patterns[:] = [PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)]
    project.analyses[:] = [StaticCase(id=1, name="sway", n_steps=1, pattern_ids=[1])]
    return project


def test_a_pinned_portal_with_a_rigid_girder_matches_the_closed_form(tmp_path: Path) -> None:
    project, frame = _project(
        roof=RoofType.MONO_PITCH,
        support=SupportCondition.PINNED,
        rigid_girder=True,
    )
    _with_sway(project, frame)
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / "sway")

    # The two eave nodes move together: the girder is axially rigid.
    left = results.node_disp[frame.top_node_ids[0]][0][0]
    right = results.node_disp[frame.top_node_ids[1]][0][0]
    assert left == pytest.approx(right, rel=1e-9)

    # A finite girder is a little more flexible than the rigid one, never stiffer.
    assert left == pytest.approx(SWAY_CLASSICAL, rel=0.02)
    assert left >= SWAY_CLASSICAL


def test_the_default_gable_frame_carries_gravity(tmp_path: Path) -> None:
    """No mechanism: this is what the out-of-plane restraint in the wizard buys."""
    project, frame = _project(
        roof=RoofType.GABLE,
        support=SupportCondition.FIXED,
        rigid_girder=False,
    )
    ridge = frame.ridge_node_id
    assert ridge is not None
    loads = [
        NodalLoad(node_id=node_id, forces=(0.0, 0.0, -5000.0, 0, 0, 0))
        for node_id in [*frame.top_node_ids, ridge]
    ]
    project.load_patterns[:] = [PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)]
    project.analyses[:] = [StaticCase(id=1, name="gravity", n_steps=1, pattern_ids=[1])]

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / "gravity")

    assert results.node_disp[ridge][0][2] < 0.0  # the ridge drops


def test_the_sway_is_linear_in_the_load(tmp_path: Path) -> None:
    project, frame = _project(
        roof=RoofType.MONO_PITCH,
        support=SupportCondition.PINNED,
        rigid_girder=True,
    )
    _with_sway(project, frame)
    full = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / "full")

    half_load = PlainLoadPattern(
        id=2,
        time_series_id=1,
        nodal_loads=[
            NodalLoad(node_id=node_id, forces=(H_FORCE / 4.0, 0.0, 0.0, 0, 0, 0))
            for node_id in frame.top_node_ids
        ],
    )
    project.load_patterns[:] = [half_load]
    project.analyses[:] = [StaticCase(id=2, name="half", n_steps=1, pattern_ids=[2])]
    half = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / "half")

    assert half.node_disp[frame.top_node_ids[0]][0][0] == pytest.approx(
        full.node_disp[frame.top_node_ids[0]][0][0] / 2.0,
        rel=1e-9,
    )
