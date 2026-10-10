"""File > Save As through the main window rebases record paths."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core import PathTimeSeries, Project, import_record
from opensees_studio.services import load_project, save_project

VALUES = [0.0, 0.01, -0.02, 0.015, 0.0]


def _record_backed_project(project_dir: Path) -> Path:
    data = project_dir / "data"
    data.mkdir(parents=True)
    record_file = data / "quake.txt"
    record_file.write_text("\n".join(repr(v) for v in VALUES) + "\n", encoding="ascii")
    record, values = import_record(record_file, project_dir, 1, format="single_column", dt=0.01)
    project = Project(
        ndm=2,
        ndf=3,
        ground_motions=[record],
        time_series=[PathTimeSeries(id=1, dt=0.01, values=values, record_id=1)],
    )
    return save_project(project, project_dir / "model.osmodel")


@pytest.mark.gui
def test_file_save_as_rebases_record_paths(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import opensees_studio.views.main_window as mod
    from opensees_studio.views.main_window import MainWindow

    src = _record_backed_project(tmp_path / "proj")
    dest = tmp_path / "other" / "model.osmodel"
    monkeypatch.setattr(
        mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(dest), ""))
    )

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(src)

    window._act_save_as.trigger()

    assert window._vm.path == dest
    assert window._vm.project.ground_motions[0].source_path == "../proj/data/quake.txt"
    reopened = load_project(dest)
    assert reopened.ground_motions[0].source_path == "../proj/data/quake.txt"
    assert reopened.ground_motions[0].status == "ok"
    assert reopened.time_series[0].values == VALUES
    # The original file is untouched.
    assert load_project(src).ground_motions[0].source_path == "data/quake.txt"
