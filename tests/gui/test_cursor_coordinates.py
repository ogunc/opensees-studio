"""The status bar shows the model point under the pointer, in the project's units."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    yield mw
    mw._help_controller.uninstall()


def test_the_readout_names_the_point_and_its_snap(window) -> None:
    window._vm.new_project(ndm=3, ndf=6)
    window._canvas.cursorMoved.emit((1.5, 0.0, 3.0, "grid"))
    assert window._cursor_label.text() == "X 1.500  Y 0.000  Z 3.000 m  (grid)"
    window._canvas.cursorMoved.emit((2.0, 0.0, 3.0, "on_element"))
    assert window._cursor_label.text().endswith("(on member)")
    window._canvas.cursorMoved.emit(None)
    assert window._cursor_label.text() == ""


def test_a_2d_model_shows_x_and_z_only(window) -> None:
    window._vm.new_project(ndm=2, ndf=3)
    window._canvas.cursorMoved.emit((4.0, 0.0, 2.5, "plane"))
    assert window._cursor_label.text() == "X 4.000  Z 2.500 m  (plane)"


def test_moving_over_the_view_reports_a_point(window, qtbot) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    window._vm.new_project(ndm=3, ndf=6)
    window.show()
    qtbot.waitExposed(window)
    canvas = window._canvas
    canvas.view_xy()  # looking down Z: the Z = 0 plane faces the pointer
    seen: list[object] = []
    canvas.cursorMoved.connect(seen.append)
    centre = QPointF(canvas.width() / 2, canvas.height() / 2)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        centre,
        canvas.mapToGlobal(centre),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(move)
    points = [p for p in seen if isinstance(p, tuple)]
    assert points, seen
    assert points[-1][3] == "plane"
    assert points[-1][2] == pytest.approx(0.0)
    assert window._cursor_label.text().startswith("X ")
