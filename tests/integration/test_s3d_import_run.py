"""A PORTICO model imported, scaled and solved by OpenSees.

The cantilevers check the translation end to end against closed form: a tip load
in each direction exercises the swap of PORTICO's local axes (its ``Iz`` is the
strong axis of a beam, OpenSees' ``Iy``), the shear areas and the unit factors.

The parity test solves PORTICO's own verification models and compares them with
the OpenSeesPy runs PORTICO publishes. Its files are not copied into this
repository: point ``PORTICO_CORE_DIR`` at a checkout of ``jpreyes/portico-core``
to run it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import ModalCase, UnitSystem
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.s3d_import import import_s3d

E, G = 2.8e7, 1.2e7  # kN/m²
A, IZ, IY, J = 0.15, 3.125e-3, 1.125e-3, 2.0e-3  # m², m⁴ (PORTICO axes: Iz strong)
AVY, AVZ = 0.125, 0.10
L, P = 4.0, 10.0  # m, kN


def _cantilever(mode: str, load: list[float]) -> dict[str, Any]:
    free = {"ux": 0, "uy": 0, "uz": 0, "rx": 0, "ry": 0, "rz": 0}
    return {
        "units": "kN-m",
        "mode": mode,
        "nodes": [
            {"id": 1, "x": 0, "y": 0, "z": 0, "restraints": dict.fromkeys(free, 1)},
            {"id": 2, "x": L, "y": 0, "z": 0, "restraints": free},
        ],
        "elements": [{"id": 1, "n1": 1, "n2": 2, "matId": 1, "secId": 1}],
        "materials": [{"id": 1, "name": "M", "E": E, "G": G, "nu": 0.2, "rho": 0}],
        "sections": [
            {"id": 1, "name": "S", "A": A, "Iz": IZ, "Iy": IY, "J": J, "Avy": AVY, "Avz": AVZ}
        ],
        "loadCases": [
            {
                "id": 1,
                "name": "TIP",
                "type": "static",
                "loads": [{"type": "nodal", "nodeId": 2, "F": load}],
            }
        ],
    }


def _tip(path: Path, data: dict[str, Any], units: UnitSystem) -> tuple[np.ndarray, Any]:
    path.write_text(json.dumps(data), encoding="utf-8")
    imported = import_s3d(path, units=units)
    project = imported.project
    results = OpenSeesRunner(project).run(project.analyses[0])
    return results.node_disp[2][-1], imported.scale


def _timoshenko(inertia: float, shear_area: float) -> float:
    return P * L**3 / (3 * E * inertia) + P * L / (G * shear_area)


def test_vertical_tip_load_bends_about_portico_strong_axis(tmp_path: Path) -> None:
    disp, scale = _tip(
        tmp_path / "v.s3d", _cantilever("3D", [0, 0, -P, 0, 0, 0]), UnitSystem.SI_M_N
    )
    assert scale.force == 1000.0
    assert -disp[2] == pytest.approx(_timoshenko(IZ, AVY), rel=1e-9)


def test_lateral_tip_load_bends_about_portico_weak_axis(tmp_path: Path) -> None:
    disp, _ = _tip(tmp_path / "h.s3d", _cantilever("3D", [0, P, 0, 0, 0, 0]), UnitSystem.SI_M_N)
    assert disp[1] == pytest.approx(_timoshenko(IY, AVZ), rel=1e-9)


def test_a_2d_cantilever_in_millimetres(tmp_path: Path) -> None:
    disp, scale = _tip(
        tmp_path / "2d.s3d", _cantilever("2D", [0, 0, -P, 0, 0, 0]), UnitSystem.SI_MM_N
    )
    # 2D results are Ux, Uz, Ry; the deflection comes back in millimetres.
    assert -disp[1] / scale.length == pytest.approx(_timoshenko(IZ, AVY), rel=1e-9)


def test_imported_shells_carry_their_self_weight(tmp_path: Path) -> None:
    """A slab of shells on four columns: the reactions add up to the weight."""
    free = {"ux": 0, "uy": 0, "uz": 0, "rx": 0, "ry": 0, "rz": 0}
    a, h, rho, col = 4.0, 0.2, 2.5, 3.0  # m, m, t/m³, m
    nodes = []
    for k, (x, y) in enumerate([(0, 0), (a, 0), (a, a), (0, a)], start=1):
        nodes.append({"id": k, "x": x, "y": y, "z": col, "restraints": free})
        nodes.append({"id": k + 4, "x": x, "y": y, "z": 0.0, "restraints": dict.fromkeys(free, 1)})
    data = {
        "units": "kN-m",
        "nodes": nodes,
        "elements": [{"id": k, "n1": k + 4, "n2": k, "matId": 1, "secId": 1} for k in range(1, 5)],
        "areas": [
            {"id": 1, "nodes": [1, 2, 3, 4], "matId": 1, "thickness": h, "behavior": "shell"}
        ],
        "materials": [{"id": 1, "name": "C", "E": 2.8e7, "G": 1.2e7, "nu": 0.2, "rho": rho}],
        "sections": [{"id": 1, "name": "C40", "A": 0.16, "Iz": 2e-3, "Iy": 2e-3, "J": 3e-3}],
        "loadCases": [{"id": 1, "name": "PP", "type": "static", "selfWeight": True, "loads": []}],
    }
    path = tmp_path / "slab.s3d"
    path.write_text(json.dumps(data), encoding="utf-8")
    project = import_s3d(path).project
    results = OpenSeesRunner(project).run(project.analyses[0])
    total = sum(results.node_reaction[k][-1][2] for k in range(5, 9))
    g = 9.80665
    weight = rho * 1000 * g * (a * a * h + 4 * 0.16 * col)  # N
    assert total == pytest.approx(weight, rel=1e-9)


def _braced_frame(member_flags: dict[int, str]) -> dict[str, Any]:
    """SAP2000 Example 1-012: a 120 x 120 in frame, an X-brace, 100 kip at the top."""
    free = {"ux": 0, "uy": 0, "uz": 0, "rx": 0, "ry": 0, "rz": 0}
    pin = {"ux": 1, "uy": 1, "uz": 1, "rx": 1, "ry": 0, "rz": 1}
    hold = {**free, "uy": 1, "rx": 1, "rz": 1}
    members = [(1, 2), (3, 4), (2, 4), (1, 4), (2, 3)]
    return {
        "units": "kip-in",
        "nodes": [
            {"id": 1, "x": 0, "y": 0, "z": 0, "restraints": pin},
            {"id": 2, "x": 0, "y": 0, "z": 120, "restraints": hold},
            {"id": 3, "x": 120, "y": 0, "z": 0, "restraints": pin},
            {"id": 4, "x": 120, "y": 0, "z": 120, "restraints": hold},
        ],
        "elements": [
            {
                "id": k,
                "n1": a,
                "n2": b,
                "matId": 1,
                "secId": 1,
                # Axial members, as in the example: a negligible bending inertia.
                **({member_flags[k]: True} if k in member_flags else {}),
            }
            for k, (a, b) in enumerate(members, start=1)
        ],
        "materials": [{"id": 1, "name": "Steel", "E": 30000, "G": 11500, "nu": 0.3, "rho": 0}],
        "sections": [{"id": 1, "name": "Bar", "A": 8, "Iz": 1e-3, "Iy": 1e-3, "J": 1e-3}],
        "loadCases": [
            {
                "id": 1,
                "name": "H",
                "type": "static",
                "loads": [{"type": "nodal", "nodeId": 2, "F": [100, 0, 0, 0, 0, 0]}],
            }
        ],
    }


@pytest.mark.parametrize(
    ("flags", "ux"),
    [({}, 0.1068), ({5: "cable"}, 0.2414), ({4: "compressionOnly"}, 0.1914)],
    ids=["linear", "cable", "strut"],
)
def test_tension_and_compression_only_members(
    tmp_path: Path, flags: dict[int, str], ux: float
) -> None:
    """The three models of SAP2000 Example 1-012 (independent and SAP2000: same values)."""
    path = tmp_path / "brace.s3d"
    path.write_text(json.dumps(_braced_frame(flags)), encoding="utf-8")
    project = import_s3d(path).project
    results = OpenSeesRunner(project).run(project.analyses[0])
    assert results.node_disp[2][-1][0] == pytest.approx(ux, rel=2e-3)
    # The base takes the whole horizontal load, split by which diagonal works.
    total = results.node_reaction[1][-1][0] + results.node_reaction[3][-1][0]
    assert total == pytest.approx(-100.0, rel=1e-6)


# ──────────────────── parity with PORTICO's own OpenSees runs ────────────────────
PORTICO = os.environ.get("PORTICO_CORE_DIR")

PARITY_CASES = {
    "1-005": "verif_1-005a_settlement",
    "1-010": "verif_1-010_link_offset",
    "1-014": "verif_1-014_modal_cantilever",
    "1-018": "verif_1-018_static_portal",
    "1-021": "verif_1-021_modal_bathe_wilson",
}


@pytest.mark.skipif(not PORTICO, reason="PORTICO_CORE_DIR points to no portico-core checkout")
@pytest.mark.parametrize("case", sorted(PARITY_CASES))
def test_matches_portico_opensees_runs(case: str) -> None:
    root = Path(str(PORTICO))
    reference = json.loads(
        (root / "tools" / "verif" / "opensees" / "results" / f"{case}.json").read_text()
    )
    imported = import_s3d(root / "examples" / f"{PARITY_CASES[case]}.s3d")
    project, scale = imported.project, imported.scale
    if reference["_meta"]["analysis"] == "modal":
        modal = ModalCase(
            id=project.next_analysis_id(), name="Modal", n_modes=len(reference["omega2"])
        )
        project.analyses.append(modal)
        results = OpenSeesRunner(project).run(modal)
        assert np.asarray(results.eigenvalues) == pytest.approx(reference["omega2"], rel=1e-8)
        return
    static = next(c for c in project.analyses if c.id == reference.get("lcId", 1))
    results = OpenSeesRunner(project).run(static)
    slots = [0, 2, 4] if project.ndm == 2 else list(range(6))
    for node, expected in reference["disp"].items():
        ours = results.node_disp[int(node)][-1]
        back = [ours[k] / (scale.length if slot < 3 else 1.0) for k, slot in enumerate(slots)]
        assert back == pytest.approx([expected[s] for s in slots], abs=1e-9)
    for node, expected in reference["reaction"].items():
        if int(node) not in results.node_reaction:
            continue
        ours = results.node_reaction[int(node)][-1]
        back = [
            ours[k] / (scale.force if slot < 3 else scale.moment) for k, slot in enumerate(slots)
        ]
        assert back == pytest.approx([expected[s] for s in slots], abs=1e-8)
