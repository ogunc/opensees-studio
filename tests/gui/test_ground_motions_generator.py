"""Ground Motions dialog, GM-3: sine and sine-beat generator."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import IEEE693_BEAT_PRESET, PathTimeSeries, TrigTimeSeries, gravity


def _open(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._act_ground_motions.trigger()
    dlg = mw._ground_motions_dlg
    assert dlg is not None
    qtbot.addWidget(dlg)
    return mw, dlg


@pytest.mark.gui
def test_sine_beat_creates_series_with_expected_npts_and_undo_removes_it(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    project = mw._vm.project
    gen = dlg.generator_dialog()
    qtbot.addWidget(gen)
    gen.set_kind("sine-beat")
    gen.set_preset(IEEE693_BEAT_PRESET.label)
    assert "engineer to confirm" in gen.preset_label()
    gen._amplitude.setValue(0.3)
    gen._frequency.setValue(2.0)
    gen._dt.setValue(0.005)

    # the live preview draws the trace and its spectrum
    times, accel = gen.preview_curve_data()
    n_beat, n_pause = round(10 / 2.0 / 0.005), round(2.0 / 0.005)
    expected = 5 * n_beat + 4 * n_pause + 1
    assert len(times) == len(accel) == expected
    assert float(max(abs(accel))) == pytest.approx(0.3, rel=1e-12)
    assert gen.spectrum_curve_count() == 1
    assert "embedded Path series" in gen.info_text()

    assert dlg.apply_generator(gen)
    assert len(project.time_series) == 1
    ts = project.time_series[0]
    assert isinstance(ts, PathTimeSeries)
    assert len(ts.values) == expected
    assert ts.dt == pytest.approx(0.005)
    assert ts.file_path == "generated:sine-beat"
    assert ts.factor == pytest.approx(gravity(project.meta.units))  # amplitude in g
    assert ts.generator["kind"] == "sine-beat" and ts.generator["units"] == "g"
    assert ts.generator["n_beats"] == 5 and ts.generator["cycles_per_beat"] == 10
    assert project.ground_motions == []  # never a record
    assert dlg._generated_list.count() == 1
    assert dlg.selected_generated_id() == ts.id

    mw._vm.undo_stack.undo()
    assert project.time_series == []
    assert dlg._generated_list.count() == 0
    mw._vm.undo_stack.redo()
    assert len(project.time_series) == 1


@pytest.mark.gui
def test_plain_sine_becomes_trig_series_and_edit_reopens_stored_parameters(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    project = mw._vm.project
    g = gravity(project.meta.units)
    gen = dlg.generator_dialog()
    qtbot.addWidget(gen)
    gen.set_kind("sine")
    gen._name.setText("Shake 1.5 Hz")
    gen._amplitude.setValue(0.25)
    gen._frequency.setValue(1.5)
    gen._duration.setValue(8.0)
    assert "native Trig series" in gen.info_text()
    assert dlg.apply_generator(gen)

    ts = project.time_series[0]
    assert isinstance(ts, TrigTimeSeries)
    assert ts.name == "Shake 1.5 Hz"
    assert ts.factor == pytest.approx(0.25 * g)
    assert ts.period == pytest.approx(1.0 / 1.5)
    assert ts.t_end == pytest.approx(8.0)
    assert ts.generator["amplitude"] == pytest.approx(0.25)

    # reopening shows the stored parameters
    again = dlg.generator_dialog(ts.id)
    qtbot.addWidget(again)
    assert again._kind.currentData() == "sine"
    assert again._name.text() == "Shake 1.5 Hz"
    assert again._amplitude.value() == pytest.approx(0.25)
    assert again._frequency.value() == pytest.approx(1.5)
    assert again._duration.value() == pytest.approx(8.0)
    assert again._units.currentData() == "g"

    # editing with ramps turns it into an embedded Path series with the same id
    again._ramp_in.setValue(2.0)
    again._ramp_out.setValue(2.0)
    assert dlg.apply_generator(again)
    edited = project.time_series[0]
    assert len(project.time_series) == 1
    assert isinstance(edited, PathTimeSeries) and edited.id == ts.id
    assert edited.file_path == "generated:sine"
    assert edited.values[0] == 0.0 and edited.values[-1] == 0.0
    assert edited.factor == pytest.approx(g)
    assert edited.generator["ramp_in_cycles"] == 2.0

    mw._vm.undo_stack.undo()
    assert isinstance(project.time_series[0], TrigTimeSeries)
    assert project.time_series[0].factor == pytest.approx(0.25 * g)


@pytest.mark.gui
def test_preview_overlays_target_and_preset_edit_becomes_custom(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    assert dlg.set_target_tbdy(sds=1.0, sd1=0.4)
    gen = dlg.generator_dialog()
    qtbot.addWidget(gen)
    gen.set_kind("sine-beat")
    assert gen.spectrum_curve_count() == 2  # generated + target
    gen.set_preset(IEEE693_BEAT_PRESET.label)
    assert gen._beats.value() == 5
    gen._beats.setValue(3)
    assert gen.preset_label() == "Custom"
    gen.set_preset(IEEE693_BEAT_PRESET.label)
    assert gen._beats.value() == 5
    assert mw._vm.project.time_series == []  # nothing applied by previewing
