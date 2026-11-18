"""Design → Concrete Frame Check: the dialog runs the check and stores its settings."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy")

from tools.verification_manual import aci_beam_project

from opensees_studio.services.opensees_runner import OpenSeesRunner


@pytest.mark.gui
def test_the_dialog_checks_the_beam(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.concrete_design import ConcreteDesignDialog

    project = aci_beam_project()
    results = {1: OpenSeesRunner(project).run(project.analyses[0])}
    dialog = ConcreteDesignDialog(project, results)
    qtbot.addWidget(dialog)
    dialog.run()
    report = dialog.report()
    # The D-15 beam is overloaded on purpose: 270 kN·m against φMn = 147 kN·m.
    assert report is not None and [m.status for m in report.members] == ["NG", "NG"]
    assert dialog._table.rowCount() == 2
    assert dialog._ratios.isEnabled()
    settings = dialog.settings()
    assert settings.concrete is not None and settings.concrete.transverse == "tied"
