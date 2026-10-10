"""Full-precision numeric input: scientific notation, exact read-back, ranges."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import Qt
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDialog

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import Node
from opensees_studio.views.dialogs.assign_masses import AssignMassesDialog
from opensees_studio.views.float_field import FloatField, format_float

FIFTEEN_DIGITS = "0.123456789012345"


def _type(qtbot, field: FloatField, text: str) -> None:  # type: ignore[no-untyped-def]
    """Replace the field's text by typing, then commit with Enter."""
    field.lineEdit().selectAll()
    qtbot.keyClicks(field, text)
    qtbot.keyClick(field, Qt.Key.Key_Return)


def _mass_field(qtbot) -> FloatField:  # type: ignore[no-untyped-def]
    field = FloatField()
    qtbot.addWidget(field)
    field.setRange(0.0, 1e12)
    return field


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1e-10, "1e-10"),
        (29000.0, "29000"),
        (2.9e4, "29000"),
        (0.1 + 0.2, "0.30000000000000004"),
        (-0.0, "0"),
        (1e16, "1e+16"),
        (float(FIFTEEN_DIGITS), FIFTEEN_DIGITS),
    ],
)
def test_format_float_is_the_shortest_round_trip(value: float, text: str) -> None:
    assert format_float(value) == text
    assert float(format_float(value)) == value


@pytest.mark.gui
@pytest.mark.parametrize("text", ["1e-10", "1E-10", "0.0000000001", "2.9e4", FIFTEEN_DIGITS])
def test_typed_value_reads_back_exactly(qtbot, text: str) -> None:  # type: ignore[no-untyped-def]
    field = _mass_field(qtbot)
    _type(qtbot, field, text)
    assert field.value() == float(text)
    assert field.text() == format_float(float(text))


@pytest.mark.gui
def test_fifteen_significant_digits_round_trip_through_the_text(qtbot) -> None:  # type: ignore[no-untyped-def]
    field = _mass_field(qtbot)
    field.setValue(123456789.012345)
    assert field.text() == "123456789.012345"
    again = _mass_field(qtbot)
    _type(qtbot, again, field.text())
    assert again.value() == field.value() == 123456789.012345


@pytest.mark.gui
@pytest.mark.parametrize("text", ["-5", "1e13", "abc", "1e400"])
def test_input_outside_the_range_or_not_a_number_is_refused(qtbot, text: str) -> None:  # type: ignore[no-untyped-def]
    field = _mass_field(qtbot)
    field.setValue(7.0)
    _type(qtbot, field, text)
    field.clearFocus()
    assert field.value() == 7.0
    assert field.text() == "7"


@pytest.mark.gui
def test_validator_states(qtbot) -> None:  # type: ignore[no-untyped-def]
    field = _mass_field(qtbot)
    state = {
        text: field.validate(text, len(text))[0]
        for text in ("1e-10", "1e", "1e-", ".", "", "-", "1e13", "abc", "nan")
    }
    acceptable, intermediate, invalid = (
        QValidator.State.Acceptable,
        QValidator.State.Intermediate,
        QValidator.State.Invalid,
    )
    assert state == {
        "1e-10": acceptable,
        "1e": intermediate,
        "1e-": intermediate,
        ".": intermediate,
        "": intermediate,
        "-": intermediate,
        "1e13": intermediate,  # out of range: never accepted, may still be edited
        "abc": invalid,
        "nan": invalid,
    }


@pytest.mark.gui
def test_suffix_and_special_value_text_still_work(qtbot) -> None:  # type: ignore[no-untyped-def]
    field = FloatField()
    qtbot.addWidget(field)
    field.setRange(0.0, 1.0)
    field.setSpecialValueText("spectrum damping")
    field.setValue(0.0)
    assert field.text() == "spectrum damping"
    field.setSuffix(" s")
    field.setValue(0.025)
    assert field.text() == "0.025 s"
    assert field.valueFromText(field.text()) == 0.025


@pytest.mark.gui
def test_assign_masses_dialog_keeps_1e_minus_10(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = AssignMassesDialog(n_selected=1, ndf=3)
    qtbot.addWidget(dlg)
    _type(qtbot, dlg._mx, "1e-10")
    _type(qtbot, dlg._my, "1e-10")
    assert dlg.mass_vector()[:2] == (1e-10, 1e-10)


def _window_with_node(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.apply_command(AddNodesCommand(mw._vm, [Node(id=1, coords=(0, 0, 0))]))
    return mw


@pytest.mark.gui
def test_assign_masses_menu_stores_1e_minus_10_exactly(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_node(qtbot)

    def _fake_exec(self: AssignMassesDialog) -> int:
        _type(qtbot, self._mx, "1e-10")
        _type(qtbot, self._mz, "2.5e-11")
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignMassesDialog, "exec", _fake_exec)
    mw._canvas.selection.select_node(1)
    mw._act_assign_masses.trigger()
    assert mw._vm.project.node(1).mass[0] == 1e-10
    assert mw._vm.project.node(1).mass[2] == 2.5e-11


@pytest.mark.gui
def test_property_editor_mass_stores_1e_minus_10_and_shows_it(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_node(qtbot)
    mw._canvas.selection.select_node(1)
    spins = mw._props._mass_spins
    _type(qtbot, spins[0], "1e-10")
    _type(qtbot, spins[1], FIFTEEN_DIGITS)
    mw._props._apply_mass_btn.click()
    mass = mw._vm.project.node(1).mass
    assert mass[0] == 1e-10 and mass[1] == float(FIFTEEN_DIGITS)
    # the dock is rebuilt from the model: the fields show the stored values
    mw._canvas.selection.select_node(1)
    assert [s.text() for s in mw._props._mass_spins[:2]] == ["1e-10", FIFTEEN_DIGITS]
