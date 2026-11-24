"""Hovering a joint or a member shows what it is; a joint wins over the members at it."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

pytestmark = pytest.mark.gui


def test_the_window_feeds_both_providers(qtbot) -> None:
    from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
    from opensees_studio.core import ElasticBeamColumn, Node, make_default_section
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        window._vm.new_project()
        vm = window._vm
        vm.apply_command(
            AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(4, 0, 0))])
        )
        vm.apply_command(AddSectionsCommand(vm, [make_default_section(1)]))
        vm.apply_command(
            AddElementsCommand(vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)])
        )
        assert window._canvas.node_tooltip is not None
        assert window._canvas.node_tooltip(2).startswith("Joint 2")
        assert window._canvas.element_tooltip(1).startswith("ElasticBeamColumn 1")
    finally:
        window._help_controller.uninstall()


def test_the_nearer_of_joint_and_member_wins(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QToolTip

    from opensees_studio.views.canvas3d import ModelCanvas
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    shown: list[str] = []
    monkeypatch.setattr(QToolTip, "showText", lambda _pos, text, _w=None: shown.append(text))
    try:
        canvas: ModelCanvas = window._canvas
        canvas.node_tooltip = lambda nid: f"joint {nid}"
        canvas.element_tooltip = lambda eid: f"member {eid}"
        # On the joint: joint and member are both at 0 px, the joint wins the tie.
        monkeypatch.setattr(canvas, "_nearest_node", lambda x, y: (5, 0.0))
        monkeypatch.setattr(canvas, "_nearest_frame", lambda x, y: (9, 0.0, 200.0))
        canvas._update_element_tooltip(10.0, 10.0)
        # Mid-span of a short member, 8 px from its joint: the member is nearer.
        monkeypatch.setattr(canvas, "_nearest_node", lambda x, y: (5, 8.0))
        canvas._update_element_tooltip(20.0, 10.0)
        # Away from everything: no tooltip.
        monkeypatch.setattr(canvas, "_nearest_frame", lambda x, y: (9, 40.0, 200.0))
        monkeypatch.setattr(canvas, "_nearest_node", lambda x, y: (5, 40.0))
        canvas._update_element_tooltip(90.0, 90.0)
        assert shown == ["joint 5", "member 9"]
        assert canvas._tooltip_element is None
    finally:
        window._help_controller.uninstall()


def test_the_deformed_shape_and_the_modes_hover_joints_only(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QToolTip

    from opensees_studio.views.canvas3d import ModelCanvas
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    shown: list[str] = []
    monkeypatch.setattr(QToolTip, "showText", lambda _pos, text, _w=None: shown.append(text))
    try:
        canvas: ModelCanvas = window._canvas
        canvas.node_tooltip = lambda nid: f"joint {nid}"
        canvas.element_tooltip = lambda eid: f"member {eid}"
        # 15 px from the joint, on the member: in the model the member answers.
        monkeypatch.setattr(canvas, "_nearest_node", lambda x, y: (5, 15.0))
        monkeypatch.setattr(canvas, "_nearest_frame", lambda x, y: (9, 0.0, 200.0))
        canvas._update_element_tooltip(10.0, 10.0)
        for mode in ("deformed", "mode"):
            window._post_mode = mode
            canvas._tooltip_element = None
            # The member is ignored and the joint answers from a little further away.
            canvas._update_element_tooltip(10.0, 10.0)
            # Far from any joint: nothing, not the member under the pointer.
            monkeypatch.setattr(canvas, "_nearest_node", lambda x, y: (5, 30.0))
            canvas._update_element_tooltip(12.0, 10.0)
            monkeypatch.setattr(canvas, "_nearest_node", lambda x, y: (5, 15.0))
        assert shown == ["member 9", "joint 5", "joint 5"]
    finally:
        window._post_mode = None
        window._help_controller.uninstall()
