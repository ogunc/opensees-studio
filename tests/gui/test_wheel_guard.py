"""Scroll safety in actual case forms and numeric inputs."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QSpinBox

from opensees_studio.views.dialogs.case_forms import PushoverCaseForm
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.wheel_guard import install_wheel_guard

pytestmark = pytest.mark.gui


def wheel(widget):
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(widget.mapToGlobal(QPoint(5, 5))),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_unfocused_constraints_scrolls_case_form(qtbot):
    install_wheel_guard()
    form = PushoverCaseForm([], [])
    scroll = QScrollArea()
    qtbot.addWidget(scroll)
    scroll.setWidget(form)
    scroll.resize(500, 200)
    scroll.show()
    form._name_edit.setFocus()
    qtbot.waitUntil(lambda: form._name_edit.hasFocus())
    value = form._constraints.currentText()
    wheel(form._constraints)
    assert form._constraints.currentText() == value
    assert scroll.verticalScrollBar().value() > 0


@pytest.mark.parametrize("cls", [QSpinBox, FloatField])
def test_numeric_wheel_requires_focus(qtbot, cls):
    install_wheel_guard()
    form = PushoverCaseForm([], [])
    qtbot.addWidget(form)
    field = cls(form)
    field.setRange(0, 100)
    field.setValue(20)
    form._layout.addRow(field)
    form.show()
    form._name_edit.setFocus()
    qtbot.waitUntil(lambda: form._name_edit.hasFocus())
    wheel(field)
    assert field.value() == 20
    field.setFocus()
    qtbot.waitUntil(lambda: field.hasFocus())
    wheel(field)
    assert field.value() < 20
