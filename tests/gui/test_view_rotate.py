"""View → Rotate: the camera turns, the model does not."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import ElasticBeamColumn, Node, make_default_section


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(4, 0, 3))])
    )
    vm.apply_command(AddSectionsCommand(vm, [make_default_section(1)]))
    vm.apply_command(AddElementsCommand(vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)]))
    mw._on_view_iso()
    return mw


def _direction(mw) -> np.ndarray:  # type: ignore[no-untyped-def]
    camera = mw._canvas.camera
    d = np.asarray(camera.position) - np.asarray(camera.focal_point)
    return d / np.linalg.norm(d)


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip(a @ b, -1.0, 1.0))))


def _heading(direction: np.ndarray) -> float:
    """Angle of the line of sight in plan (about the vertical Z axis)."""
    return float(np.degrees(np.arctan2(direction[1], direction[0])))


@pytest.mark.gui
def test_each_step_turns_the_view_15_degrees_and_back(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    project_before = mw._vm.project.model_dump()
    start = _direction(mw)

    mw._act_rotate_right.trigger()
    turned = (_heading(_direction(mw)) - _heading(start) + 180.0) % 360.0 - 180.0
    assert abs(turned) == pytest.approx(15.0, abs=0.5)
    mw._act_rotate_left.trigger()
    assert _angle(start, _direction(mw)) == pytest.approx(0.0, abs=0.5)

    mw._act_rotate_up.trigger()
    assert _angle(start, _direction(mw)) == pytest.approx(15.0, abs=0.5)
    mw._act_rotate_down.trigger()
    assert _angle(start, _direction(mw)) == pytest.approx(0.0, abs=0.5)
    assert mw._vm.project.model_dump() == project_before  # only the camera moved


@pytest.mark.gui
def test_rotating_leaves_a_plane_view(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._act_view_top.trigger()
    cleared: list[bool] = []
    original = mw._canvas.clear_working_plane
    mw._canvas.clear_working_plane = lambda: (cleared.append(True), original())[1]  # type: ignore[method-assign]
    mw._act_rotate_left.trigger()
    assert cleared


@pytest.mark.gui
def test_spin_turns_until_switched_off(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    start = _direction(mw)
    mw._act_spin.setChecked(True)
    assert mw._canvas.is_spinning
    qtbot.waitUntil(lambda: _angle(start, _direction(mw)) > 3.0, timeout=3000)
    mw._act_spin.setChecked(False)
    assert not mw._canvas.is_spinning
    stopped = _direction(mw)
    qtbot.wait(200)
    # One already-scheduled spin tick can still move the camera by a few 1e-7
    # radians on a slow runner; the assertion is that spin is off, not that the
    # camera is frozen to the last floating-point bit.
    assert _angle(stopped, _direction(mw)) == pytest.approx(0.0, abs=1e-5)
