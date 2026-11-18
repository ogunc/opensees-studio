"""SAP2000 text models imported, scaled and solved by OpenSees.

The cantilever checks the translation against closed form: a vertical tip load
bends a beam about SAP2000's local 3 (``I33``, shear on ``AS2``) and a lateral
one about local 2 (``I22``, ``AS3``), in kN-m read into newtons. The portal and
the 3D frame are the hand-written fixtures: the portal's reactions balance its
loads, and the 3D frame solves to the same displacements after a trip through
the writer.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.sap2000_text import export_s2k, import_s2k

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "s2k"

E, G = 2.0e8, 8.0e7  # kN/m²
A, I33, I22, J, AS2, AS3 = 0.01, 4e-5, 1e-5, 2e-5, 0.004, 0.006
L, P = 3.0, 10.0  # m, kN

_CANTILEVER = f"""\
TABLE:  "PROGRAM CONTROL"
   ProgramName=SAP2000   CurrUnits="KN, m, C"
TABLE:  "JOINT COORDINATES"
   Joint=1   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=0
   Joint=2   CoordSys=GLOBAL   CoordType=Cartesian   XorR={L}   Y=0   Z=0
TABLE:  "JOINT RESTRAINT ASSIGNMENTS"
   Joint=1   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=STEEL   UnitWeight=0   UnitMass=0   E1={E}   G12={G}
TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"
   SectionName=S   Material=STEEL   Shape=General   Area={A}   TorsConst={J} _
      I33={I33}   I22={I22}   AS2={AS2}   AS3={AS3}
TABLE:  "CONNECTIVITY - FRAME"
   Frame=1   JointI=1   JointJ=2
TABLE:  "FRAME SECTION ASSIGNMENTS"
   Frame=1   AnalSect=S   MatProp=Default
TABLE:  "LOAD PATTERN DEFINITIONS"
   LoadPat=TIP   SelfWtMult=0
TABLE:  "JOINT LOADS - FORCE"
   Joint=2   LoadPat=TIP   CoordSys=GLOBAL   F1=0   F2={{f2}}   F3={{f3}}
END TABLE DATA
"""


def _tip(tmp_path: Path, f2: float, f3: float) -> np.ndarray:
    path = tmp_path / "cantilever.s2k"
    path.write_text(_CANTILEVER.format(f2=f2, f3=f3), encoding="utf-8")
    project = import_s2k(path).project
    results = OpenSeesRunner(project).run(project.analyses[0])
    return np.asarray(results.node_disp[2][-1])


def _timoshenko(inertia: float, shear_area: float) -> float:
    """Tip deflection in metres of the kN-m cantilever (forces in N, stiffness in N/m²)."""
    return P * L**3 / (3 * E * inertia) + P * L / (G * shear_area)


def test_vertical_tip_load_bends_about_local_3(tmp_path: Path) -> None:
    disp = _tip(tmp_path, 0.0, -P)
    assert -disp[2] == pytest.approx(_timoshenko(I33, AS2), rel=1e-9)


def test_lateral_tip_load_bends_about_local_2(tmp_path: Path) -> None:
    disp = _tip(tmp_path, P, 0.0)
    assert disp[1] == pytest.approx(_timoshenko(I22, AS3), rel=1e-9)


def test_the_portal_reactions_balance_its_loads() -> None:
    project = import_s2k(FIXTURES / "portal_2d.s2k").project
    runner = OpenSeesRunner(project)
    live = next(c for c in project.analyses if c.name == "LIVE")
    wind = next(c for c in project.analyses if c.name == "WIND")
    dead = next(c for c in project.analyses if c.name == "DEAD")
    # 2D results are (Fx, Fz, My) per node; supports are joints 1 and 4.
    live_r = runner.run(live).node_reaction
    assert live_r[1][-1][1] + live_r[4][-1][1] == pytest.approx(10_000 * 6, rel=1e-9)
    wind_r = runner.run(wind).node_reaction
    assert wind_r[1][-1][0] + wind_r[4][-1][0] == pytest.approx(-20_000, rel=1e-9)
    dead_r = runner.run(dead).node_reaction
    weight = 24_000 * 0.15 * (4 + 6 + 4)
    assert dead_r[1][-1][1] + dead_r[4][-1][1] == pytest.approx(weight, rel=1e-9)


def test_the_3d_frame_solves_the_same_after_a_round_trip(tmp_path: Path) -> None:
    first = import_s2k(FIXTURES / "frame_3d.s2k").project
    export_s2k(first, tmp_path / "again.s2k")
    again = import_s2k(tmp_path / "again.s2k").project
    for name in ("DEAD", "LIVE", "EQX", "GRAV"):
        case_a = next(c for c in first.analyses if c.name == name)
        case_b = next(c for c in again.analyses if c.name == name)
        disp_a = OpenSeesRunner(first).run(case_a).node_disp
        disp_b = OpenSeesRunner(again).run(case_b).node_disp
        scale = max(float(np.max(np.abs(d[-1]))) for d in disp_a.values())
        assert scale > 0, name
        for node_id, values in disp_a.items():
            np.testing.assert_allclose(
                disp_b[node_id][-1], values[-1], rtol=1e-9, atol=1e-9 * scale, err_msg=name
            )
