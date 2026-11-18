"""Rigid diaphragms, the mass source and the storey table against hand-built OpenSeesPy.

The bundled ``building_3storey_diaphragm`` example (3 storeys, 2 x 2 bays,
one storey diaphragm per floor with its retained node at the centre of mass,
mass from DEAD + 0.3 LIVE) is rebuilt here by hand in plain OpenSeesPy, with
the floor masses worked out in this file, not taken from the application:

* with ``rigidDiaphragm`` and the floor mass and polar inertia lumped at the
  centre of mass: every period must match the application's;
* with ``equalDOF`` in X only, the floor mass in X on a master node: the
  X-sway periods must match (a doubly symmetric frame sways in X without
  twisting, so the in-plane rigidity in Y and rotation does not enter).

The static lateral case checks the storey table: storey shears are the
inverted-triangle forces summed from the top, the base shear the sum of the
reactions, the drift ratios the hand model's storey displacements over 3.5 m.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core.storey_results import base_shear_from_reactions, storey_profile
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "building_3storey_diaphragm.osmodel"

#: The hand model, run in a fresh interpreter (one eigen call per process, as
#: the eigen determinism rule asks). Prints the eigenvalues, then the CM
#: displacements under the lateral forces, as one JSON line.
_HAND_MODEL = r"""
import json, sys
import numpy as np
import openseespy.opensees as ops

variant = sys.argv[1]
G = 9.80665
xs, ys, zs = (0.0, 6.0, 12.0), (0.0, 5.0, 10.0), (0.0, 3.5, 7.0, 10.5)
gamma = 25_000.0
col = dict(A=0.25, Iz=0.005208333333333333, Iy=0.005208333333333333, J=0.0088)
beam = dict(A=0.18, Iz=0.0054, Iy=0.00135, J=0.0037)
E, Gm = 30e9, 12.5e9
q_dead, q_live = 15_000.0, 10_000.0

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)
tag = {}
n = 1
for k, z in enumerate(zs):
    for y in ys:
        for x in xs:
            ops.node(n, x, y, z)
            if k == 0:
                ops.fix(n, 1, 1, 1, 1, 1, 1)
            tag[(x, y, z)] = n
            n += 1
ops.geomTransf("Linear", 1, 1.0, 0.0, 0.0)  # columns
ops.geomTransf("Linear", 2, 0.0, 0.0, 1.0)  # beams

weight = {}  # joint -> weight lumped from member self weight and floor loads
def lump(a, b, w_per_m, length):
    for t in (a, b):
        weight[t] = weight.get(t, 0.0) + 0.5 * w_per_m * length

e = 1
for k in range(1, len(zs)):
    for y in ys:
        for x in xs:
            a, b = tag[(x, y, zs[k - 1])], tag[(x, y, zs[k])]
            ops.element("elasticBeamColumn", e, a, b, col["A"], E, Gm, col["J"], col["Iy"], col["Iz"], 1)
            lump(a, b, gamma * col["A"], zs[k] - zs[k - 1]); e += 1
    beams = [((xs[i], y), (xs[i + 1], y)) for y in ys for i in range(2)]
    beams += [((x, ys[j]), (x, ys[j + 1])) for x in xs for j in range(2)]
    for (x1, y1), (x2, y2) in beams:
        a, b = tag[(x1, y1, zs[k])], tag[(x2, y2, zs[k])]
        ops.element("elasticBeamColumn", e, a, b, beam["A"], E, Gm, beam["J"], beam["Iy"], beam["Iz"], 2)
        length = abs(x2 - x1) + abs(y2 - y1)
        lump(a, b, gamma * beam["A"] + q_dead + 0.3 * q_live, length); e += 1

masters = []
for k in range(1, len(zs)):
    z = zs[k]
    floor = [tag[(x, y, z)] for y in ys for x in xs]
    m = {t: weight[t] / G for t in floor}
    total = sum(m.values())
    master = 1000 + k
    masters.append(master)
    ops.node(master, 6.0, 5.0, z)
    if variant == "diaphragm":
        polar = sum(m[t] * ((ops.nodeCoord(t)[0] - 6.0) ** 2 + (ops.nodeCoord(t)[1] - 5.0) ** 2) for t in floor)
        ops.fix(master, 0, 0, 1, 1, 1, 0)
        ops.rigidDiaphragm(3, master, *floor)
        ops.mass(master, total, total, 0.0, 0.0, 0.0, polar)
    else:
        ops.fix(master, 0, 1, 1, 1, 1, 1)
        for t in floor:
            ops.equalDOF(master, t, 1)
        ops.mass(master, total, 0.0, 0.0, 0.0, 0.0, 0.0)

n_modes = 9 if variant == "diaphragm" else 3
eig = ops.eigen("-fullGenLapack", n_modes)

disp = []
if variant == "diaphragm":
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for master, f in zip(masters, (100_000.0, 200_000.0, 300_000.0)):
        ops.load(master, f, 0.0, 0.0, 0.0, 0.0, 0.0)
    ops.system("BandGeneral"); ops.numberer("RCM"); ops.constraints("Transformation")
    ops.test("NormDispIncr", 1e-8, 25); ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0); ops.analysis("Static")
    assert ops.analyze(1) == 0
    disp = [ops.nodeDisp(master, 1) for master in masters]
print("HAND_JSON " + json.dumps({"eig": list(eig), "disp": disp}))
"""


def _hand(variant: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _HAND_MODEL, variant],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    line = next(x for x in proc.stdout.splitlines() if x.startswith("HAND_JSON "))
    import json

    return json.loads(line[len("HAND_JSON ") :])


def _fresh_modal(case_id: int) -> np.ndarray:
    """The application's eigenvalues, from a fresh process like the CLI's."""
    script = (
        "import sys, json\n"
        "from opensees_studio.services import load_project\n"
        "from opensees_studio.services.opensees_runner import OpenSeesRunner\n"
        "p = load_project(sys.argv[1])\n"
        "c = next(c for c in p.analyses if c.id == int(sys.argv[2]))\n"
        "r = OpenSeesRunner(p).run(c)\n"
        "print('APP_JSON ' + json.dumps([float(v) for v in r.eigenvalues]))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(EXAMPLE), str(case_id)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    import json

    line = next(x for x in proc.stdout.splitlines() if x.startswith("APP_JSON "))
    return np.array(json.loads(line[len("APP_JSON ") :]))


def test_diaphragm_periods_match_the_hand_built_rigid_diaphragm_model() -> None:
    app = _fresh_modal(3)
    hand = np.array(_hand("diaphragm")["eig"])
    assert app.shape == hand.shape == (9,)
    np.testing.assert_allclose(app, hand, rtol=1e-9, atol=0.0)


def test_x_sway_periods_match_the_hand_built_equal_dof_model() -> None:
    project = load_project(EXAMPLE)
    case = next(c for c in project.analyses if c.id == 3)
    result = OpenSeesRunner(project).run(case)
    from opensees_studio.services.spectrum import mass_participation

    x_modes = [
        m.mode_number - 1 for m in mass_participation(project, result, 1) if m.mass_ratio > 1e-6
    ]
    assert len(x_modes) == 3
    hand = np.array(_hand("equal_dof")["eig"])
    np.testing.assert_allclose(result.eigenvalues[x_modes], hand, rtol=1e-9, atol=0.0)


def test_static_storey_table_matches_hand_forces_and_displacements() -> None:
    project = load_project(EXAMPLE)
    case = next(c for c in project.analyses if c.name == "EQX")
    result = OpenSeesRunner(project).run(case)

    shears = [
        result.storey_shear[s.id][-1] for s in sorted(project.storeys, key=lambda s: s.elevation)
    ]
    np.testing.assert_allclose([v[0] for v in shears], [600e3, 500e3, 300e3], rtol=1e-9)
    np.testing.assert_allclose([v[1] for v in shears], 0.0, atol=1e-6)
    last = {nid: values[-1] for nid, values in result.node_reaction.items()}
    np.testing.assert_allclose(base_shear_from_reactions(project, last), [600e3, 0.0], atol=1e-6)

    profile = storey_profile(project, {nid: v[-1] for nid, v in result.node_disp.items()})
    hand = np.array(_hand("diaphragm")["disp"])
    np.testing.assert_allclose(profile.disp[:, 0], hand, rtol=1e-9)
    expected_drift = np.diff(np.concatenate([[0.0], hand])) / 3.5
    np.testing.assert_allclose(profile.drift[:, 0], expected_drift, rtol=1e-9)
