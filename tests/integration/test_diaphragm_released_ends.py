"""Frame end releases at rigid-diaphragm joints against hand-built OpenSeesPy.

The ``building_3storey_diaphragm`` example gets released beam ends at joints
its floor diaphragms constrain. OpenSees' Transformation handler cannot chain
a hidden release node's ``equalDOF`` through the diaphragm (it solves without a
warning and gives T1 = 0.06 s instead of 1.02 s here), so the runner releases
such an end inside the element, or holds it with penalty springs (see
``services/frame_members.py``). Each variant is checked against references
built by hand in this file, each in a fresh interpreter (one eigen call per
process, as the eigen determinism rule asks):

* **pinned beams** (X beams: M2 and M3 at end i; Y beams: T and M2 at end j):
  periods and both static cases against elements released with
  ``-releasez`` / ``-releasey`` and ``J = 0``, and the static cases against an
  independent formulation, hidden nodes tied by ``equalDOF`` solved with the
  Lagrange handler (which does chain constraints exactly, but cannot run an
  eigen analysis);
* **partial fixity** (X beams: M2 and M3 springs at end i): periods and the
  lateral case against ``ModElasticBeam3d`` carrying the series stiffness of
  member and springs (exact without element loads), both static cases against
  the Lagrange model. The runner's penalty springs are 1e5 times the member's
  stiffness, which leaves about 1e-7 (measured); the tolerance is 1e-6. (The
  two references agree with each other to 1e-14 on the lateral case.)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.services import load_project, save_project
from opensees_studio.services.opensees_runner import OpenSeesRunner

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "building_3storey_diaphragm.osmodel"

K2, K3 = 2.0e7, 5.0e7  # partial-fixity stiffness (N m / rad) of the X beams' end i

#: Both variants: element name prefix -> (end, released, springs).
VARIANTS: dict[str, dict[str, tuple[str, tuple[str, ...], dict[str, float]]]] = {
    "pinned": {"BX": ("i", ("M2", "M3"), {}), "BY": ("j", ("T", "M2"), {})},
    "fixity": {"BX": ("i", ("M2", "M3"), {"M2": K2, "M3": K3})},
}

_HAND_MODEL = r"""
import json, sys
import numpy as np
import openseespy.opensees as ops

variant, form, case = sys.argv[1], sys.argv[2], sys.argv[3]
xs, ys, zs = (0.0, 6.0, 12.0), (0.0, 5.0, 10.0), (0.0, 3.5, 7.0, 10.5)
gamma = 25_000.0
col = dict(A=0.25, Iz=0.005208333333333333, Iy=0.005208333333333333, J=0.0088)
beam = dict(A=0.18, Iz=0.0054, Iy=0.00135, J=0.0037)
E, Gm = 30e9, 12.5e9
q_dead, q_live = 15_000.0, 10_000.0
K2, K3 = 2.0e7, 5.0e7

# Global rotation DOF of each local release with vecxz = +Z: an X beam has
# local (x, y, z) = (X, Y, Z), a Y beam (Y, -X, Z).
ROT = {"X": {"T": 4, "M2": 5, "M3": 6}, "Y": {"T": 5, "M2": 4, "M3": 6}}
if variant == "pinned":
    released = {"X": ("i", ("M2", "M3"), {}), "Y": ("j", ("T", "M2"), {})}
else:
    released = {"X": ("i", ("M2", "M3"), {"M2": K2, "M3": K3})}

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

def series(EI, L, k):
    # Basic bending stiffness of a member with an end-i spring k, over EI / L.
    flex = L / (6.0 * EI) * np.array([[2.0, -1.0], [-1.0, 2.0]]) + np.diag([1.0 / k, 0.0])
    s = np.linalg.inv(flex) * L / EI
    return s[0, 0], s[1, 1], s[0, 1]

weight = {}
def lump(a, b, w_per_m, length):
    for t in (a, b):
        weight[t] = weight.get(t, 0.0) + 0.5 * w_per_m * length

hidden = 5000
lagrange_ties = []  # (joint, hidden node, tied dofs, {dof: spring})
columns, beams_x = [], []
e = 1
for k in range(1, len(zs)):
    for y in ys:
        for x in xs:
            a, b = tag[(x, y, zs[k - 1])], tag[(x, y, zs[k])]
            ops.element("elasticBeamColumn", e, a, b, col["A"], E, Gm, col["J"], col["Iy"], col["Iz"], 1)
            columns.append(e)
            lump(a, b, gamma * col["A"], zs[k] - zs[k - 1]); e += 1
    pairs = [("X", (xs[i], y), (xs[i + 1], y)) for y in ys for i in range(2)]
    pairs += [("Y", (x, ys[j]), (x, ys[j + 1])) for x in xs for j in range(2)]
    for axis, (x1, y1), (x2, y2) in pairs:
        a, b = tag[(x1, y1, zs[k])], tag[(x2, y2, zs[k])]
        length = abs(x2 - x1) + abs(y2 - y1)
        lump(a, b, gamma * beam["A"] + q_dead + 0.3 * q_live, length)
        beams_x.append(e)
        props = [beam["A"], E, Gm, beam["J"], beam["Iy"], beam["Iz"], 2]
        if axis not in released:
            ops.element("elasticBeamColumn", e, a, b, *props); e += 1
            continue
        end, dofs, springs = released[axis]
        if form == "elem":
            code = 1 if end == "i" else 2
            args = []
            if "M3" in dofs: args += ["-releasez", code]
            if "M2" in dofs: args += ["-releasey", code]
            J = 0.0 if "T" in dofs else beam["J"]
            ops.element("elasticBeamColumn", e, a, b, beam["A"], E, Gm, J, beam["Iy"], beam["Iz"], 2, *args)
        elif form == "mod":
            ky = series(E * beam["Iy"], length, springs["M2"])
            kz = series(E * beam["Iz"], length, springs["M3"])
            ops.element("ModElasticBeam3d", e, a, b, beam["A"], E, Gm, beam["J"], beam["Iy"], beam["Iz"], *ky, *kz, 2)
        else:  # lagrange: a hidden node at the released end
            joint = a if end == "i" else b
            ops.node(hidden, *ops.nodeCoord(joint))
            kept = [ROT[axis][d] for d in ("T", "M2", "M3") if d not in dofs]
            lagrange_ties.append((joint, hidden, [1, 2, 3, *kept], {ROT[axis][d]: v for d, v in springs.items()}))
            ends = (hidden, b) if end == "i" else (a, hidden)
            ops.element("elasticBeamColumn", e, *ends, *props)
            hidden += 1
        e += 1

masters = []
for k in range(1, len(zs)):
    z = zs[k]
    floor = [tag[(x, y, z)] for y in ys for x in xs]
    m = {t: weight[t] / 9.80665 for t in floor}
    total = sum(m.values())
    master = 1000 + k
    masters.append(master)
    ops.node(master, 6.0, 5.0, z)
    polar = sum(m[t] * ((ops.nodeCoord(t)[0] - 6.0) ** 2 + (ops.nodeCoord(t)[1] - 5.0) ** 2) for t in floor)
    ops.fix(master, 0, 0, 1, 1, 1, 0)
    ops.rigidDiaphragm(3, master, *floor)
    ops.mass(master, total, total, 0.0, 0.0, 0.0, polar)
mat = 1
for joint, node, dofs, springs in lagrange_ties:
    ops.equalDOF(joint, node, *dofs)
    if springs:
        tags = []
        for dof, value in sorted(springs.items()):
            ops.uniaxialMaterial("Elastic", mat, value); tags.append(mat); mat += 1
        ops.element("zeroLength", 9000 + mat, joint, node, "-mat", *tags, "-dir", *sorted(springs))

out = {}
if case == "modal":
    out["eig"] = list(ops.eigen("-fullGenLapack", 9))
else:
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    if case == "EQX":
        for master, f in zip(masters, (100_000.0, 200_000.0, 300_000.0)):
            ops.load(master, f, 0.0, 0.0, 0.0, 0.0, 0.0)
    else:  # DEAD: beam loads plus self weight, local z up on the beams
        for el in columns:
            ops.eleLoad("-ele", el, "-type", "-beamUniform", 0.0, 0.0, -gamma * col["A"])
        for el in beams_x:
            ops.eleLoad("-ele", el, "-type", "-beamUniform", 0.0, -(q_dead + gamma * beam["A"]), 0.0)
    ops.system("UmfPack"); ops.numberer("RCM")
    ops.constraints("Lagrange" if form == "lagrange" else "Transformation")
    ops.test("NormDispIncr", 1e-8, 25); ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0); ops.analysis("Static")
    assert ops.analyze(1) == 0
    nodes = sorted(tag.values()) + masters
    out["disp"] = {str(t): ops.nodeDisp(t) for t in nodes}
print("HAND_JSON " + json.dumps(out))
"""

_APP = r"""
import json, sys
import numpy as np
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
p = load_project(sys.argv[1])
c = next(c for c in p.analyses if c.name == sys.argv[2])
r = OpenSeesRunner(p).run(c)
if sys.argv[2] == "Modal":
    out = {"eig": [float(v) for v in r.eigenvalues]}
else:
    out = {"disp": {str(n): [float(x) for x in v[-1]] for n, v in r.node_disp.items()}}
print("APP_JSON " + json.dumps(out))
"""


def _run(script: str, *args: str, marker: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", script, *args], capture_output=True, text=True, timeout=300
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    line = next(x for x in proc.stdout.splitlines() if x.startswith(marker))
    return json.loads(line[len(marker) :])


@pytest.fixture(scope="module", params=sorted(VARIANTS))
def released(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory):
    """The example with the variant's releases, saved for the analysis subprocesses."""
    project = load_project(EXAMPLE)
    for k, el in enumerate(project.elements):
        spec = VARIANTS[request.param].get(el.name[:2])
        if spec is None:
            continue
        end, dofs, springs = spec
        release = EndRelease(released=dofs, springs=springs)
        releases = FrameReleases(i=release) if end == "i" else FrameReleases(j=release)
        project.elements[k] = el.model_copy(update={"releases": releases})
    path = tmp_path_factory.mktemp(request.param) / "building.osmodel"
    save_project(project, path)
    return request.param, path


def _app(path: Path, case: str) -> dict:
    return _run(_APP, str(path), case, marker="APP_JSON ")


def _hand(variant: str, form: str, case: str) -> dict:
    return _run(_HAND_MODEL, variant, form, case, marker="HAND_JSON ")


def _disp(result: dict) -> np.ndarray:
    """Displacements in node order, the three CM nodes (37-39 / 1001-1003) last."""
    by_node = result["disp"]
    keys = sorted(by_node, key=int)
    return np.array([by_node[k] for k in keys])


def _tolerance(variant: str) -> float:
    return 1e-9 if variant == "pinned" else 1e-6


def test_the_released_building_runs_without_the_hidden_equal_dof_chain(released) -> None:
    variant, path = released
    project = load_project(path)
    runner = OpenSeesRunner(project)
    runner.build()
    plan = runner._frame_plan
    if variant == "pinned":
        # Every release sits at a diaphragm joint and is condensed in the element.
        assert not plan.nodes and not plan.equal_dofs
        codes = {m.release_args for m in plan.members.values() if m.release_args}
        assert codes == {("-releasez", 1, "-releasey", 1), ("-releasey", 2)}
    else:
        # Partial fixity: hidden nodes held by springs, still no equalDOF.
        assert len(plan.nodes) == len(plan.springs) == 18 and not plan.equal_dofs


def test_periods_match_the_hand_built_model(released) -> None:
    variant, path = released
    app = np.array(_app(path, "Modal")["eig"])
    hand = np.array(_hand(variant, "elem" if variant == "pinned" else "mod", "modal")["eig"])
    assert app.shape == hand.shape == (9,)
    np.testing.assert_allclose(app, hand, rtol=_tolerance(variant), atol=0.0)
    # Through the hidden nodes' equalDOF chain T1 came out 0.06 s (pinned).
    assert 2 * np.pi / np.sqrt(app[0]) > 0.6


@pytest.mark.parametrize("case", ["EQX", "DEAD"])
def test_static_cases_match_the_hand_built_models(released, case: str) -> None:
    variant, path = released
    app = _disp(_app(path, case))
    references = ["lagrange"]
    if variant == "pinned" or case == "EQX":
        references.append("elem" if variant == "pinned" else "mod")
    for form in references:
        hand = _disp(_hand(variant, form, case))
        assert app.shape == hand.shape == (39, 6)
        # Relative to the largest translation / rotation anywhere in the building.
        scale = np.repeat([np.abs(hand[:, :3]).max(), np.abs(hand[:, 3:]).max()], 3)
        error = np.abs(app - hand) / scale
        assert error.max() <= _tolerance(variant), (form, error.max())
