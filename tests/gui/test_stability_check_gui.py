"""Analyze → Check Model Stability from the window, through the child process."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from opensees_studio.commands import AddElementsCommand, AddMaterialsCommand, AddNodesCommand
from opensees_studio.core import ElasticUniaxial, Node, TrussElement
from opensees_studio.services.stability import StabilityReport


def _window(qtbot, *, diagonal: bool):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=2, ndf=2)
    vm = mw._vm
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(
                    id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)
                ),
                Node(
                    id=2,
                    coords=(4.0, 0.0, 0.0),
                    restraint=(False, False, True, False, False, False),
                ),
                Node(id=3, coords=(4.0, 0.0, 3.0)),
                Node(id=4, coords=(0.0, 0.0, 3.0)),
            ],
        )
    )
    vm.apply_command(AddMaterialsCommand(vm, [ElasticUniaxial(id=1, E=2e8)]))
    pairs = [(1, 2), (2, 3), (3, 4), (4, 1)] + ([(1, 3)] if diagonal else [])
    vm.apply_command(
        AddElementsCommand(
            vm,
            [TrussElement(id=k, nodes=p, area=0.01, material_id=1) for k, p in enumerate(pairs, 1)],
        )
    )
    mw._refresh_action_enablement()
    return mw


@pytest.mark.gui
def test_the_action_lives_in_the_analyze_menu_and_needs_a_project(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    assert mw._act_check_stability.text() == "Check Model &Stability…"
    menus = {a.text(): a.menu() for a in mw.menuBar().actions()}
    assert mw._act_check_stability in menus["&Analyze"].actions()
    assert mw._act_cancel_stability in menus["&Analyze"].actions()
    assert not mw._act_cancel_stability.isEnabled()


@pytest.mark.gui
def test_a_mechanism_is_reported_and_its_joints_selected(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, diagonal=False)
    assert mw._act_check_stability.isEnabled()
    with qtbot.waitSignal(mw._stability.finished, timeout=60000) as blocker:
        mw._act_check_stability.trigger()
    report = blocker.args[0]
    assert not report.stable and report.n_mechanisms == 1
    assert mw._canvas.selection.nodes == frozenset({3, 4})
    box = mw._stability_box
    assert box is not None and box.icon() == QMessageBox.Icon.Warning
    assert "not statically stable" in box.text()
    assert "N3 Ux" in box.informativeText() or "N4 Ux" in box.informativeText()
    box.close()


@pytest.mark.gui
def test_a_braced_truss_is_reported_stable(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, diagonal=True)
    with qtbot.waitSignal(mw._stability.finished, timeout=60000) as blocker:
        mw._act_check_stability.trigger()
    assert blocker.args[0].stable
    assert "statically stable" in mw._stability_box.text()
    mw._stability_box.close()


@pytest.mark.gui
def test_an_incomplete_check_is_not_called_unstable(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._on_stability_report(
        StabilityReport(
            n_equations=5,
            rank=None,
            completion="partial",
            classification="no_mechanisms",
            failure_reason="the sparse search only checked the lowest modes",
        )
    )
    assert "incomplete" in mw._stability_box.text()
    assert "not statically stable" not in mw._stability_box.text()
    mw._stability_box.close()
