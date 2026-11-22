"""The draw tools' dashed preview of the element the next click would create."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from opensees_studio.commands import AddNodesCommand, AddSectionsCommand
from opensees_studio.core import Node, Project
from opensees_studio.core.sections import ElasticMembranePlateSection
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.canvas3d import SelectionState
from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
from opensees_studio.views.tools.draw_frame import DrawFrameTool
from opensees_studio.views.tools.draw_shell import DrawShellTool
from opensees_studio.views.tools.draw_truss import DrawTrussTool

Point = tuple[float, float, float]


class _PreviewCanvas(QObject):
    """A canvas stub that reports the pointer and records the preview."""

    cursorMoved = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.selection = SelectionState()
        self.preview: tuple[list[Point], bool] | None = None
        self.clears = 0

    def set_snap_preview_enabled(self, _enabled: bool) -> None:
        pass

    def set_snap_reference(self, _point: Point | None) -> None:
        pass

    def set_draw_preview(self, points: list[Point], *, closed: bool = False) -> None:
        self.preview = (list(points), closed)

    def clear_draw_preview(self) -> None:
        self.preview = None
        self.clears += 1


def _vm(ndm: int = 3) -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project(ndm=ndm, ndf=6 if ndm == 3 else 3)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0, 0, 0)),
                Node(id=2, coords=(4, 0, 0)),
                Node(id=3, coords=(4, 0, 3)),
            ],
        )
    )
    return vm


@pytest.mark.gui
@pytest.mark.parametrize("tool_class", [DrawFrameTool, DrawTrussTool])
def test_member_preview_follows_the_pointer_from_the_first_point(qtbot, tool_class) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    canvas = _PreviewCanvas()
    tool = tool_class(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    # Nothing placed yet: hovering shows only the snap marker.
    canvas.cursorMoved.emit((4.0, 0.0, 0.0, "grid"))
    assert canvas.preview is None

    tool.on_node_picked(1)
    canvas.cursorMoved.emit((4.0, 0.0, 3.0, "node"))
    assert canvas.preview == ([(0.0, 0.0, 0.0), (4.0, 0.0, 3.0)], False)

    # A member snap and the bare working plane are clickable points too.
    canvas.cursorMoved.emit((2.0, 0.0, 0.0, "midpoint"))
    assert canvas.preview == ([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], False)
    canvas.cursorMoved.emit((1.5, 0.0, 2.5, "plane"))
    assert canvas.preview is not None and canvas.preview[0][-1] == (1.5, 0.0, 2.5)

    # The pointer left the view: no point to preview to.
    canvas.cursorMoved.emit(None)
    assert canvas.preview is None


@pytest.mark.gui
def test_member_preview_restarts_from_the_end_of_the_chain(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    canvas = _PreviewCanvas()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_node_picked(1)
    canvas.cursorMoved.emit((4.0, 0.0, 0.0, "node"))
    tool.on_node_picked(2)  # creates frame 1-2, the chain continues from 2

    canvas.cursorMoved.emit((4.0, 0.0, 3.0, "node"))
    assert canvas.preview == ([(4.0, 0.0, 0.0), (4.0, 0.0, 3.0)], False)

    tool.reset()  # Esc
    assert canvas.preview is None
    canvas.cursorMoved.emit((0.0, 0.0, 0.0, "node"))
    assert canvas.preview is None


@pytest.mark.gui
def test_deactivating_the_tool_removes_the_preview_and_stops_listening(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    canvas = _PreviewCanvas()
    tool = DrawTrussTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_node_picked(1)
    canvas.cursorMoved.emit((4.0, 0.0, 0.0, "grid"))
    assert canvas.preview is not None

    tool.deactivate()
    assert canvas.preview is None
    canvas.cursorMoved.emit((4.0, 0.0, 3.0, "grid"))
    assert canvas.preview is None


@pytest.mark.gui
def test_a_2d_preview_stays_in_the_xz_plane(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm(ndm=2)
    canvas = _PreviewCanvas()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_node_picked(1)
    canvas.cursorMoved.emit((2.0, 0.4, 3.0, "plane"))
    assert canvas.preview == ([(0.0, 0.0, 0.0), (2.0, 0.0, 3.0)], False)


@pytest.mark.gui
def test_shell_preview_is_a_closed_outline_through_the_pointer(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(
        AddSectionsCommand(vm, [ElasticMembranePlateSection(id=1, E=3e10, nu=0.2, h=0.2)])
    )
    canvas = _PreviewCanvas()
    tool = DrawShellTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    canvas.cursorMoved.emit((4.0, 0.0, 0.0, "node"))
    assert canvas.preview == ([(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], True)

    tool.on_node_picked(2)
    tool.on_node_picked(3)
    canvas.cursorMoved.emit((0.0, 0.0, 3.0, "grid"))
    assert canvas.preview == (
        [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 0.0, 3.0), (0.0, 0.0, 3.0)],
        True,
    )

    tool.on_empty_clicked(0.0, 0.0, 3.0)  # the fourth corner closes the shell
    assert canvas.preview is None


@pytest.mark.gui
def test_draw_tools_snap_the_hover_to_joints(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A click on a joint reuses it, so the preview must end on the joint too."""
    assert DrawFrameTool.wants_node_snap
    assert DrawTrussTool.wants_node_snap
    assert DrawShellTool.wants_node_snap


@pytest.mark.gui
def test_canvas_draws_and_removes_the_dashed_outline(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(Project(nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))]))
    renderer = canvas._renderer

    canvas.set_draw_preview([(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 0.0, 3.0)], closed=True)
    actor = renderer._draw_preview_actor
    assert actor is not None
    points = np.asarray(actor.GetMapper().GetInput().GetPoints().GetData())
    # Three dashed sides of 24 dashes, two points per dash.
    assert points.shape == (3 * 24 * 2, 3)
    assert points[:, 1] == pytest.approx(0.0)
    assert points[:, 0].max() == pytest.approx(4.0)
    assert points[:, 2].max() == pytest.approx(3.0)

    # A zero-length preview (the pointer on the first point) draws nothing.
    canvas.set_draw_preview([(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)])
    assert renderer._draw_preview_actor is None

    canvas.set_draw_preview([(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)])
    assert renderer._draw_preview_actor is not None
    canvas.clear_draw_preview()
    assert renderer._draw_preview_actor is None

    # A model refresh drops the transient outline with the rest of the scene.
    canvas.set_draw_preview([(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)])
    canvas.refresh(Project(nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))]))
    assert renderer._draw_preview_actor is None
