"""Unit tests for ModelRenderer using off-screen PyVista.

These don't need Qt — the renderer is plotter-agnostic. We exercise it
against a regular ``pv.Plotter(off_screen=True)``.
"""

from __future__ import annotations

import pytest

pv = pytest.importorskip("pyvista")
import numpy as np  # noqa: E402

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    Steel01,
    TrussElement,
)
from opensees_studio.views.canvas3d.model_renderer import (  # noqa: E402
    ModelRenderer,
    _classify_support,
)


# ──────────────────────────── support classification ────────────────────────────
def test_classify_support_full_fix() -> None:
    assert _classify_support((True,) * 6, (0, 1, 2, 3, 4, 5)) == "fix"


def test_classify_support_pin_3d() -> None:
    assert _classify_support(
        (True, True, True, False, False, False), (0, 1, 2, 3, 4, 5)
    ) == "pin"


def test_classify_support_pin_2d() -> None:
    assert _classify_support(
        (True, True, False, False, False, False), (0, 1)
    ) == "fix"  # in 2D-2DOF, "all flags True" means fix
    # 2D pin (truss): both translations fixed, no rotation in DOF set → fix
    # In 2D-3DOF, pin would be (Ux, Uy fixed, Rz free):
    assert _classify_support(
        (True, True, False, False, False, False), (0, 1, 5)
    ) == "pin"


def test_classify_support_roller() -> None:
    assert _classify_support(
        (False, True, False, False, False, False), (0, 1, 5)
    ) == "roller"


# ──────────────────────────── renderer ────────────────────────────
@pytest.fixture
def offscreen_plotter():  # type: ignore[no-untyped-def]
    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True)
    yield p
    p.close()


@pytest.fixture
def small_3d_project() -> Project:
    return Project(
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 3.0)),
            Node(id=3, coords=(4.0, 0, 3.0), mass=(100, 100, 0, 0, 0, 0)),
        ],
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4,
                                 Iy=1e-4, G=80e9, J=1e-6)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(0, 0, -10e3, 0, 0, 0))],
            )
        ],
    )


def test_render_empty_project_does_not_raise(offscreen_plotter) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(None)
    r.render(Project())  # also empty


def test_render_small_project_creates_actors(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    # 3 nodes + 2 elements + 1 support + 1 load + 1 mass-ring = 8 actors at minimum
    assert len(r._actors) >= 7  # support glyph counted


def test_render_clears_previous_actors(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    first_count = len(r._actors)
    r.render(small_3d_project)  # render again
    assert len(r._actors) == first_count   # not doubled


def test_picking_metadata_attached_to_node_meshes(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)

    # Inspect the plotter's actor list for our tagged meshes.
    found_node_ids = set()
    found_elem_ids = set()
    for name, actor in offscreen_plotter.actors.items():
        mesh = actor.mapper.dataset if hasattr(actor, "mapper") else None
        if mesh is None:
            continue
        if "_oss_id" not in mesh.cell_data:
            continue
        kind = str(np.asarray(mesh.cell_data["_oss_kind"])[0])
        eid = int(np.asarray(mesh.cell_data["_oss_id"])[0])
        if kind == "node":
            found_node_ids.add(eid)
        elif kind == "element":
            found_elem_ids.add(eid)

    assert found_node_ids == {1, 2, 3}
    assert found_elem_ids == {1, 2}


def test_bbox_diag_handles_degenerate_geometry() -> None:
    p = Project(nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 0, 0))])
    # Two coincident nodes → bbox extent is zero; renderer must not divide by zero.
    assert ModelRenderer._compute_bbox_diag(p) >= 1.0
