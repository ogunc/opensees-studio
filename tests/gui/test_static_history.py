"""Published Nonlinear Truss: 1001 points through GUI, storage and CSV."""

import csv

import numpy as np
import openseespy.opensees as ops
import pytest

from opensees_studio.core import (
    Hardening,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TrussElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.result_store import load_results, write_results
from opensees_studio.views.dialogs.case_forms import StaticCaseForm
from opensees_studio.views.dialogs.material_forms import HardeningForm
from opensees_studio.views.docks.results_panel import ResultsPanel

pytestmark = pytest.mark.gui
COORDS = [(0, 0), (72, 0), (168, 0), (48, 144)]


def _published_reference():
    # OpenSeesPy NonlinearTruss.py, numerical commands as published.
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 2)
    for nid, xy in enumerate(COORDS, 1):
        ops.node(nid, *xy)
    for nid in (1, 2, 3):
        ops.fix(nid, 1, 1)
    ops.uniaxialMaterial("Hardening", 1, 29000, 36, 0, 0.05 / 0.95 * 29000)
    for nid in (1, 2, 3):
        ops.element("Truss", nid, nid, 4, 4, 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(4, 160, 0)
    ops.system("ProfileSPD")
    ops.numberer("Plain")
    ops.constraints("Plain")
    ops.integrator("LoadControl", 0.001)
    ops.algorithm("Newton")
    ops.test("NormUnbalance", 1e-8, 10)
    ops.analysis("Static")
    rows = np.zeros((1001, 18))
    for step in range(1, 1001):
        assert ops.analyze(1) == 0
        ops.reactions()
        row = [step, ops.getLoadFactor(1)]
        for nid in range(1, 5):
            row.extend(ops.nodeDisp(nid))
            row.extend(ops.nodeReaction(nid))
        rows[step] = row
    return rows


def test_nonlinear_truss_1001_point_gui_history_csv(qtbot, tmp_path):
    expected = _published_reference()
    material = HardeningForm()
    qtbot.addWidget(material)
    material.populate(Hardening(id=1, E=29000, sigmaY=36, H_iso=0, H_kin=0.05 / 0.95 * 29000))
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=nid, coords=(*xy, 0), restraint=(nid < 4, nid < 4, False, False, False, False))
            for nid, xy in enumerate(COORDS, 1)
        ],
        materials=[material.read()],
        elements=[TrussElement(id=nid, nodes=(nid, 4), area=4, material_id=1) for nid in (1, 2, 3)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=4, forces=(160, 0, 0, 0, 0, 0))],
            )
        ],
    )
    form = StaticCaseForm(project.load_patterns, [])
    qtbot.addWidget(form)
    form.populate(
        StaticCase(
            id=1,
            pattern_ids=[1],
            n_steps=1000,
            load_factor_increment=0.001,
            system="ProfileSPD",
            numberer="Plain",
            algorithm="Newton",
            test="NormUnbalance",
            tolerance=1e-8,
            max_iter=10,
        )
    )
    result = OpenSeesRunner(project).run(form.read())
    assert result.node_disp[4].shape == (1001, 2)
    back = load_results(write_results(result, tmp_path), tmp_path)
    np.testing.assert_array_equal(back.load_factors, result.load_factors)
    panel = ResultsPanel()
    qtbot.addWidget(panel)
    panel.show_results(back, project)
    panel._tabs.setCurrentIndex(3)
    path = panel.export_current(tmp_path / "history.csv")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    actual = np.asarray(rows[1:], dtype=float)
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-12)
    assert panel._tabs.tabText(4) == "Static curve"
    print("Nonlinear Truss max absolute history difference:", np.max(np.abs(actual - expected)))
