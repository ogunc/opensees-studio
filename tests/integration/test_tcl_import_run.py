"""A Tcl-imported model solves: the translation preserves the mechanics.

OpenSees' own 2D examples live in its x-y plane; the project stores 2D in X-Z.
If the importer got the coordinate or DOF mapping wrong, the tip of this
cantilever would move the wrong way or not at all.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

ops = pytest.importorskip("openseespy.opensees")  # skip if OpenSeesPy not installed

from opensees_studio.core import StaticCase, UnitSystem  # noqa: E402
from opensees_studio.services import OpenSeesRunner  # noqa: E402
from opensees_studio.services.tcl_import import import_tcl  # noqa: E402


def test_imported_cantilever_matches_the_closed_form(tmp_path: Path) -> None:
    L = 120.0
    P = 10.0
    E = 29000.0
    I = 100.0  # noqa: E741 - second moment of area
    path = tmp_path / "cantilever.tcl"
    path.write_text(
        f"""
model basic -ndm 2 -ndf 3
node 1 0.0 0.0
node 2 {L} 0.0
fix 1 1 1 1
section Elastic 1 {E} 10.0 {I}
geomTransf Linear 1
element elasticBeamColumn 1 1 2 10.0 {E} {I} 1
pattern Plain 1 Linear {{
    load 2 0.0 -{P} 0.0
}}
""",
        encoding="utf-8",
    )

    imported = import_tcl(path, units=UnitSystem.US_IN_KIP)
    case = StaticCase(id=1, name="Tip load", pattern_ids=[1])
    imported.project.analyses.append(case)

    results = OpenSeesRunner(imported.project).run(case)

    expected = -P * L**3 / (3.0 * E * I)
    actual = results.disp(node_id=2, dof=2)
    assert math.isclose(actual, expected, rel_tol=1e-9), (expected, actual)
