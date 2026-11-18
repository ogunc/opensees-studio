"""Section cuts solved by OpenSees, against the statics of the free body."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Group,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    SectionCut,
    StaticCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.result_tables import section_cut_table

SECTION = ElasticSection(id=1, E=2e8, A=0.01, Iz=1e-4, Iy=1e-4, G=8e7, J=1e-4)


def _solve(project: Project, tmp_path: Path):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)


def test_a_3d_cantilever_cut_at_its_base(tmp_path: Path) -> None:
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 3.0)),
        ],
        sections=[SECTION],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(10.0, 4.0, -100.0, 0.0, 0.0, 2.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="cantilever", pattern_ids=[1])],
        groups=[Group(id=1, name="base", node_ids=[1], element_ids=[1])],
        section_cuts=[SectionCut(id=1, name="BASE", group_id=1)],
    )
    forces = _solve(project, tmp_path).section_cut_forces[1][-1]
    # The loads on the column: F = (10, 4, -100) at r = (0, 0, 3), plus Mz = 2.
    expected = [10.0, 4.0, -100.0, -3 * 4.0, 3 * 10.0, 2.0]
    assert forces == pytest.approx(expected, abs=1e-9)


def test_a_2d_portal_cut_through_both_column_bases(tmp_path: Path) -> None:
    fixed = (True, False, True, False, True, False)
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=fixed),
            Node(id=2, coords=(6.0, 0.0, 0.0), restraint=fixed),
            Node(id=3, coords=(0.0, 0.0, 4.0)),
            Node(id=4, coords=(6.0, 0.0, 4.0)),
        ],
        sections=[SECTION],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 4), section_id=1),
            ElasticBeamColumn(id=3, nodes=(3, 4), section_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=3, forces=(20.0, 0.0, -50.0, 0.0, 0.0, 0.0)),
                    NodalLoad(node_id=4, forces=(0.0, 0.0, -30.0, 0.0, 0.0, 0.0)),
                ],
            )
        ],
        analyses=[StaticCase(id=1, name="portal", pattern_ids=[1])],
        groups=[Group(id=1, name="columns", node_ids=[1, 2], element_ids=[1, 2])],
        section_cuts=[SectionCut(id=1, name="BASE", group_id=1)],
    )
    results = _solve(project, tmp_path)
    fx, fy, fz, mx, my, mz = results.section_cut_forces[1][-1]
    assert (fx, fz) == pytest.approx((20.0, -80.0), abs=1e-9)
    # About the centroid (3, 0, 0): r x F, My = rz Fx - rx Fz.
    assert my == pytest.approx(4 * 20.0 - (-3) * (-50.0) - 3 * (-30.0), abs=1e-8)
    assert (fy, mx, mz) == (0.0, 0.0, 0.0)
    table = section_cut_table(results, project)
    assert table is not None
    assert table.columns[3:] == ["F1 [N]", "F3 [N]", "M2 [N·m]"]
    assert np.allclose(table.rows[0][3:], [fx, fz, my])
