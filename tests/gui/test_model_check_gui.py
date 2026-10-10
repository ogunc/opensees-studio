"""The model check in the interface: the dialog, the menu entry and the gate before Run.

The findings themselves are pinned in ``tests/unit/test_model_check.py``. What
is pinned here is what a person sees and what Run does with it: an error stops at
a list whose safe answer is the default one, a warning does not interrupt, and
nothing is shown at all for a model that is fine.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QDialogButtonBox

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.views.dialogs import ModelCheckDialog

FIXED = (True,) * 6


def _section() -> ElasticSection:
    return ElasticSection(id=1, name="S", E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _project(extra_nodes: list[Node] | None = None) -> Project:
    """A fixed cantilever, plus whatever extra nodes the test wants to leave loose."""
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIXED),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
            *(extra_nodes or []),
        ],
        sections=[_section()],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )


def _loose_node() -> Node:
    return Node(id=9, coords=(8.0, 8.0, 0.0))


def _window(qtbot, extra_nodes: list[Node] | None = None):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(mw._vm, _project(extra_nodes).nodes),
    )
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_section()]))
    mw._vm.apply_command(
        AddElementsCommand(mw._vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)])
    )
    mw._vm.project.load_patterns.append(PlainLoadPattern(id=1, name="P", time_series_id=1))
    mw._vm.project.analyses.append(StaticCase(id=1, name="Gravity", pattern_ids=[1]))
    return mw


def _button_texts(dialog: QDialog) -> list[str]:
    box = dialog.findChild(QDialogButtonBox)
    return [button.text() for button in box.buttons()]


# ──────────────────────────── the dialog ────────────────────────────
@pytest.mark.gui
def test_the_dialog_lists_each_finding_with_where_and_what_to_do(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ModelCheckDialog(_project([_loose_node()]))
    qtbot.addWidget(dialog)

    report = dialog.report()
    assert dialog._table.rowCount() == len(report.findings) == 1
    assert dialog._table.item(0, 0).text() == "Error"
    assert "Node 9" in dialog._table.item(0, 1).text()
    assert dialog._table.item(0, 2).text() == "nodes 9"
    assert dialog._table.item(0, 3).text()  # there is something to do about it
    assert "1 error" in dialog._summary.text()


@pytest.mark.gui
def test_a_clean_model_says_so(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ModelCheckDialog(_project())
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 0
    assert "passed" in dialog._summary.text()
    assert dialog._summary.level == "info"


@pytest.mark.gui
def test_select_in_canvas_hands_the_row_s_nodes_to_the_callback(qtbot) -> None:  # type: ignore[no-untyped-def]
    seen: list[tuple[list[int], list[int]]] = []
    dialog = ModelCheckDialog(
        _project([_loose_node()]),
        on_select=lambda nodes, elements: seen.append((list(nodes), list(elements))),
    )
    qtbot.addWidget(dialog)

    assert not dialog._select_button.isEnabled()  # nothing chosen yet
    dialog._table.selectRow(0)
    assert dialog._select_button.isEnabled()
    dialog._select_current()

    assert seen == [([9], [])]


@pytest.mark.gui
def test_the_check_dialog_only_closes_and_the_pre_run_one_defaults_to_cancel(qtbot) -> None:  # type: ignore[no-untyped-def]
    plain = ModelCheckDialog(_project([_loose_node()]))
    pre_run = ModelCheckDialog(_project([_loose_node()]), pre_run=True)
    qtbot.addWidget(plain)
    qtbot.addWidget(pre_run)

    assert "Close" in _button_texts(plain)
    assert "Run anyway" not in _button_texts(plain)

    assert {"Run anyway", "Cancel"} <= set(_button_texts(pre_run))
    default = next(b for b in pre_run.findChild(QDialogButtonBox).buttons() if b.isDefault())
    assert default.text() == "Cancel"  # the safe answer is the one Enter gives


# ──────────────────────────── through the menu ────────────────────────────
@pytest.mark.gui
def test_the_menu_entry_opens_the_check_and_logs_the_summary(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, [_loose_node()])
    opened: list[ModelCheckDialog] = []
    monkeypatch.setattr(
        ModelCheckDialog,
        "exec",
        lambda self: opened.append(self) or int(QDialog.DialogCode.Rejected),
    )

    assert mw._act_check_model.isEnabled()
    mw._act_check_model.trigger()

    assert len(opened) == 1
    assert not opened[0]._pre_run
    assert "Model check: 1 error." in mw._console.toPlainText()


@pytest.mark.gui
def test_the_menu_entry_is_in_the_analyze_menu_before_run(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    analyze = next(a.menu() for a in mw.menuBar().actions() if a.text() == "&Analyze")
    labels = [a.text() for a in analyze.actions() if not a.isSeparator()]
    assert labels.index("Check &Model…") < labels.index("&Run…")


# ──────────────────────────── the gate before Run ────────────────────────────
class _FakeRunDialog:
    """Stands in for the Run dialog so a test can tell whether Run got that far."""

    created = 0

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        type(self).created += 1

    def exec(self) -> int:
        return int(QDialog.DialogCode.Rejected)

    def deleteLater(self) -> None:
        pass


@pytest.fixture
def fake_run(monkeypatch):  # type: ignore[no-untyped-def]
    _FakeRunDialog.created = 0
    monkeypatch.setattr("opensees_studio.views.main_window.RunAnalysisDialog", _FakeRunDialog)
    return _FakeRunDialog


@pytest.mark.gui
def test_run_stops_at_the_list_when_the_model_has_errors(qtbot, monkeypatch, fake_run) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, [_loose_node()])
    shown: list[ModelCheckDialog] = []
    monkeypatch.setattr(
        ModelCheckDialog,
        "exec",
        lambda self: shown.append(self) or int(QDialog.DialogCode.Rejected),
    )

    mw._act_run.trigger()

    assert len(shown) == 1
    assert shown[0]._pre_run
    assert fake_run.created == 0  # cancelled: the analysis never started
    assert "Run cancelled." in mw._console.toPlainText()


@pytest.mark.gui
def test_run_anyway_goes_on_to_the_run_dialog(qtbot, monkeypatch, fake_run) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, [_loose_node()])
    monkeypatch.setattr(ModelCheckDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))

    mw._act_run.trigger()

    assert fake_run.created == 1
    assert "Running anyway." in mw._console.toPlainText()


@pytest.mark.gui
def test_a_clean_model_runs_without_any_interruption(qtbot, monkeypatch, fake_run) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)

    def refuse(self) -> int:  # type: ignore[no-untyped-def]
        raise AssertionError("a clean model must not show the check")

    monkeypatch.setattr(ModelCheckDialog, "exec", refuse)
    mw._act_run.trigger()

    assert fake_run.created == 1


@pytest.mark.gui
def test_warnings_go_to_the_console_and_do_not_interrupt(qtbot, monkeypatch, fake_run) -> None:  # type: ignore[no-untyped-def]
    # A fully restrained node nothing reaches is a warning, not an error.
    leftover = Node(id=9, coords=(8.0, 8.0, 0.0), restraint=FIXED)
    mw = _window(qtbot, [leftover])

    def refuse(self) -> int:  # type: ignore[no-untyped-def]
        raise AssertionError("a warning must not stop the run")

    monkeypatch.setattr(ModelCheckDialog, "exec", refuse)
    mw._act_run.trigger()

    assert fake_run.created == 1
    assert "Node 9 is fully restrained" in mw._console.toPlainText()
