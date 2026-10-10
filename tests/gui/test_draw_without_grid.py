"""A brand-new project has an empty grid — and drawing still has to work.

Two contract changes, both from the same report: arming a draw tool moved the
camera to top view, and a click that was not within a few pixels of a grid
*intersection* was silently dropped, so the tool looked dead.

Now:

- arming a tool never touches the camera — the user's view is theirs;
- a click resolves to a grid intersection when one is close, and otherwise to
  where the view ray meets the working plane, so a node always lands where the
  pointer was;
- with no grid at all there is no snapping, and the status line says so instead
  of a modal standing between the user and the canvas.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import SetCoordSystemsCommand
from opensees_studio.core import CoordinateGridSystem, GridSystem, make_grid_lines

#: (slot name on MainWindow, tool name shown in the prompt)
DRAW_TOOLS = [
    ("_on_draw_node_tool", "Draw Node"),
    ("_on_draw_frame_tool", "Draw Frame"),
    ("_on_draw_truss_tool", "Draw Truss"),
]


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._vm.new_project(ndm=2, ndf=3)
    win.show()
    qtbot.waitExposed(win)
    yield win


def _give_it_a_grid(window) -> None:  # type: ignore[no-untyped-def]
    window._vm.apply_command(
        SetCoordSystemsCommand(
            window._vm,
            [
                CoordinateGridSystem(
                    name="Global",
                    grid=GridSystem(
                        x_grid_lines=make_grid_lines("X", [0.0, 5.0]),
                        y_grid_lines=make_grid_lines("Y", [0.0, 3.0]),
                        z_grid_lines=make_grid_lines("Z", [0.0]),
                    ),
                )
            ],
        )
    )


@pytest.mark.parametrize(("slot", "tool_name"), DRAW_TOOLS)
@pytest.mark.gui
def test_a_draw_tool_arms_without_a_grid_and_says_what_clicks_do(  # type: ignore[no-untyped-def]
    qtbot, window, slot, tool_name
) -> None:
    assert not window._has_grid_lines()

    getattr(window, slot)()

    # It arms: an empty grid is no longer a reason to refuse.
    assert window._tool_controller.active is not None
    # ...and the status bar explains where a click will land.
    message = window.statusBar().currentMessage()
    assert message.startswith(tool_name)
    assert "No grid defined" in message
    assert "working plane" in message


@pytest.mark.gui
def test_a_project_with_a_grid_says_nothing_about_grids(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    _give_it_a_grid(window)

    window._on_draw_node_tool()

    assert window._tool_controller.active is not None
    assert "No grid defined" not in window.statusBar().currentMessage()


@pytest.mark.gui
def test_a_hidden_grid_counts_as_no_grid_for_the_hint(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    _give_it_a_grid(window)
    project = window._vm.project
    system = project.coord_systems[0]
    window._vm.apply_command(
        SetCoordSystemsCommand(
            window._vm,
            [system.model_copy(update={"grid": system.grid.model_copy(update={"visible": False})})],
        )
    )

    window._on_draw_node_tool()

    assert "No grid defined" in window.statusBar().currentMessage()
    assert window._tool_controller.active is not None  # still armed


@pytest.mark.parametrize(("slot", "tool_name"), DRAW_TOOLS)
@pytest.mark.gui
def test_arming_a_tool_does_not_move_the_camera(  # type: ignore[no-untyped-def]
    qtbot, window, slot, tool_name
) -> None:
    """The report: the view jumped as soon as a draw tool was armed."""
    canvas = window._canvas
    window._on_view_iso()
    before = (
        np.asarray(canvas.camera.position, dtype=float).copy(),
        np.asarray(canvas.camera.focal_point, dtype=float).copy(),
        np.asarray(canvas.camera.up, dtype=float).copy(),
    )

    getattr(window, slot)()

    assert window._tool_controller.active is not None
    after = (
        np.asarray(canvas.camera.position, dtype=float),
        np.asarray(canvas.camera.focal_point, dtype=float),
        np.asarray(canvas.camera.up, dtype=float),
    )
    for old, new in zip(before, after, strict=True):
        assert np.allclose(old, new), f"{tool_name} moved the camera"


@pytest.mark.gui
def test_an_off_grid_click_still_creates_a_node(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    """The other half of the report: nothing was ever drawn."""
    _give_it_a_grid(window)
    project = window._vm.project
    window._on_draw_node_tool()
    tool = window._tool_controller.active

    # The canvas reports an unsnapped point (no intersection within tolerance).
    tool.on_empty_clicked(1.25, 2.75, 0.0, False)

    assert len(project.nodes) == 1
    node = project.nodes[0]
    assert (node.coords[0], node.coords[1], node.coords[2]) == (1.25, 2.75, 0.0)
    assert "working plane" in window.statusBar().currentMessage()


@pytest.mark.gui
def test_a_snapped_click_says_it_landed_on_the_grid(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    _give_it_a_grid(window)
    window._on_draw_node_tool()
    tool = window._tool_controller.active

    tool.on_empty_clicked(5.0, 3.0, 0.0, True)

    assert tuple(project_coords(window)) == (5.0, 3.0)
    assert "on the grid" in window.statusBar().currentMessage()


def project_coords(window) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    node = window._vm.project.nodes[0]
    return node.coords[0], node.coords[1]
