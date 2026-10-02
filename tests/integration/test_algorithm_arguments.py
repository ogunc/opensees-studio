"""Live options must change solver behaviour, not merely parse successfully."""

import json
import subprocess
import sys

import pytest

PROBE = """
import json
import openseespy.opensees as o
records = []
for algorithm in ("Newton", "ModifiedNewton"):
 for args in ((), ("-initial",)):
  o.wipe(); o.model("basic", "-ndm", 1, "-ndf", 1)
  o.node(1, 0); o.node(2, 0); o.fix(1, 1)
  o.uniaxialMaterial("Steel01", 1, 10, 100, 0.1)
  o.element("zeroLength", 1, 1, 2, "-mat", 1, "-dir", 1)
  o.timeSeries("Linear", 1); o.pattern("Plain", 1, 1); o.load(2, 8)
  o.system("BandGeneral"); o.numberer("Plain"); o.constraints("Plain")
  o.test("NormDispIncr", 1e-10, 1000); o.algorithm(algorithm, *args)
  o.integrator("LoadControl", 1); o.analysis("Static")
  iterations = []
  for _ in range(3):
   assert o.analyze(1) == 0
   iterations.append(o.testIter())
  records.append([algorithm, args, iterations, o.nodeDisp(2, 1)])
o.wipe()
print(json.dumps(records))
"""


def test_initial_tangent_changes_live_iteration_behaviour():
    process = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    records = json.loads(process.stdout)
    for normal, initial in (records[:2], records[2:]):
        assert normal[2][-1] == 2
        assert initial[2][-1] > 100
        assert initial[3] == pytest.approx(normal[3], abs=1e-8)
