"""An imported IFC model solves, and to the same answer as the model it came from.

The unit tests compare the model field by field; this compares what the solver
does with it. A model exported to IFC and imported back must give the original's
displacements and reactions, and another program's portal (kN, mm) must solve to
the closed form of a statically determinate check.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy")
pytest.importorskip("ifcopenshell")

from opensees_studio.services.ifc_export import export_ifc
from opensees_studio.services.ifc_import import import_ifc
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import load_project
from tests.ifc_samples import analytical_portal

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize(
    "example", ["space_frame_3d", "portal_frame", "elastic_frame", "basic_truss"]
)
def test_the_round_trip_solves_to_the_same_displacements_and_reactions(
    example: str, tmp_path: Path
) -> None:
    src = load_project(EXAMPLES / f"{example}.osmodel")
    export_ifc(src, tmp_path / "model.ifc")
    dst = import_ifc(tmp_path / "model.ifc").project
    # Each IFC load case comes back as one pattern with its own static case.
    case = next(c for c in src.analyses if c.type == "Static" and len(c.pattern_ids) == 1)
    name = next(p.name for p in src.load_patterns if p.id == case.pattern_ids[0])
    twin = next(c for c in dst.analyses if c.name == name)

    before = OpenSeesRunner(src).run(case)
    after = OpenSeesRunner(dst).run(twin)

    for node in src.nodes:
        assert np.allclose(
            after.node_disp[node.id][-1], before.node_disp[node.id][-1], rtol=1e-8, atol=1e-12
        )
        assert np.allclose(
            after.node_reaction[node.id][-1],
            before.node_reaction[node.id][-1],
            rtol=1e-8,
            atol=1e-6,
        )


def test_another_program_s_portal_carries_its_point_load_to_the_supports(tmp_path: Path) -> None:
    """Reactions balance the applied loads: 20 kN down and 10 kN sideways on the frame."""
    project = import_ifc(analytical_portal(tmp_path / "portal.ifc")).project
    live = next(c for c in project.analyses if c.name == "LIVE")
    results = OpenSeesRunner(project).run(live)

    reactions = sum(results.node_reaction[n][-1] for n in (1, 4))
    assert reactions[0] == pytest.approx(-10_000.0, rel=1e-9)  # N, against the 10 kN push
    assert reactions[2] == pytest.approx(20_000.0, rel=1e-9)  # N, carrying the 20 kN load
