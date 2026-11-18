"""GUI tests for load combinations: the Define dialog, the case-manager guard, and Display."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.core import (
    CombinationTerm,
    LinearTimeSeries,
    LoadCombination,
    ModalCase,
    PlainLoadPattern,
    StaticCase,
)
from opensees_studio.core.code_combinations import CODES
from opensees_studio.services.results import CombinationResults, StaticResults
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.case_manager import AnalysisCaseManagerDialog
from opensees_studio.views.dialogs.load_combinations import (
    ENVELOPE_NAME,
    CodeGeneratorDialog,
    LoadCombinationsDialog,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _vm() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    project = vm.project
    assert project is not None
    project.time_series.append(LinearTimeSeries(id=1, name="Ramp"))
    project.load_patterns.extend(
        [
            PlainLoadPattern(id=1, name="DEAD", time_series_id=1),
            PlainLoadPattern(id=2, name="LIVE", time_series_id=1),
            PlainLoadPattern(id=3, name="WIND", time_series_id=1),
        ]
    )
    project.analyses.extend(
        [
            StaticCase(id=1, name="DEAD", pattern_ids=[1]),
            StaticCase(id=2, name="LIVE", pattern_ids=[2]),
            StaticCase(id=3, name="WIND", pattern_ids=[3]),
            ModalCase(id=4, name="MODAL"),
        ]
    )
    return vm


@pytest.mark.gui
def test_add_edit_and_undo_a_combination(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    project = vm.project
    assert project is not None

    dlg._add_btn.click()
    assert [c.name for c in project.combinations] == ["COMB1"]
    assert dlg.selected_id() == 1 and dlg.term_count() == 1

    dlg.set_name("ULS1")
    dlg.set_type("LinearAdd")
    dlg.set_term(0, "case", 1, 1.2)
    dlg.add_term()
    dlg.set_term(1, "case", 2, 1.6)
    assert dlg.apply()
    combo = project.combination(1)
    assert combo.name == "ULS1"
    assert [(t.ref_id, t.factor) for t in combo.terms] == [(1, 1.2), (2, 1.6)]
    assert dlg.message_level() == "info"

    vm.undo_stack.undo()  # the edit
    assert project.combination(1).name == "COMB1"
    vm.undo_stack.undo()  # the add
    assert project.combinations == []


@pytest.mark.gui
def test_only_static_and_spectrum_cases_are_offered(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    dlg._add_btn.click()
    offered = [dlg._rows[0].source.itemText(i) for i in range(dlg._rows[0].source.count())]
    assert len(offered) == 3
    assert not any("MODAL" in text for text in offered)
    with pytest.raises(ValueError, match="not offered"):
        dlg.set_term(0, "case", 4, 1.0)


@pytest.mark.gui
def test_cycles_and_empty_combinations_are_refused(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    project.combinations.extend(
        [
            LoadCombination(id=1, name="A", terms=[CombinationTerm(ref_id=1)]),
            LoadCombination(
                id=2, name="B", terms=[CombinationTerm(source="combination", ref_id=1)]
            ),
        ]
    )
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    dlg.select(1)
    dlg.set_term(0, "combination", 2, 1.0)
    assert not dlg.apply()
    assert dlg.message_level() == "error"
    assert "include each other" in dlg.message_text()
    assert project.combination(1).terms[0].source == "case"

    dlg.select(1)
    dlg._table.selectRow(0)
    dlg._on_remove_term()
    assert dlg.term_count() == 0
    assert not dlg.apply()
    assert "includes no case" in dlg.message_text()


@pytest.mark.gui
def test_adding_a_nonlinear_case_applies_with_a_warning(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    project.analyses[1] = project.analyses[1].model_copy(update={"algorithm": "Newton"})
    project.combinations.append(
        LoadCombination(
            id=1, name="C", terms=[CombinationTerm(ref_id=1), CombinationTerm(ref_id=2)]
        )
    )
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    dlg.set_term(1, "case", 2, 2.0)
    assert dlg.apply()
    assert dlg.message_level() == "warning"
    assert "superposition" in dlg.message_text()
    assert project.combination(1).terms[1].factor == 2.0


@pytest.mark.gui
def test_delete_refuses_a_combination_another_one_includes(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    project.combinations.extend(
        [
            LoadCombination(id=1, name="A", terms=[CombinationTerm(ref_id=1)]),
            LoadCombination(
                id=2, name="ENV", terms=[CombinationTerm(source="combination", ref_id=1)]
            ),
        ]
    )
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    dlg.select(1)
    dlg._delete_btn.click()
    assert [c.id for c in project.combinations] == [1, 2]
    assert "'ENV'" in dlg.message_text()

    dlg.select(2)
    dlg._delete_btn.click()
    dlg.select(1)
    dlg._delete_btn.click()
    assert project.combinations == []
    vm.undo_stack.undo()
    vm.undo_stack.undo()
    assert sorted(c.id for c in project.combinations) == [1, 2]


@pytest.mark.gui
def test_copy_makes_an_independent_combination(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    project.combinations.append(
        LoadCombination(id=1, name="A", terms=[CombinationTerm(ref_id=1, factor=1.4)])
    )
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    dlg._copy_btn.click()
    assert [c.name for c in project.combinations] == ["A", "A copy"]
    assert project.combination(2).terms == project.combination(1).terms
    assert dlg.selected_id() == 2


@pytest.mark.gui
def test_asce_generator_adds_combinations_and_an_envelope_in_one_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    cases = [c for c in project.analyses if c.type == "Static"]
    gen = CodeGeneratorDialog(cases)
    qtbot.addWidget(gen)
    # The case names give the roles.
    assert gen.roles() == {"D": [1], "L": [2], "W": [3]}
    gen.set_role(3, None)
    assert gen.roles() == {"D": [1], "L": [2]}

    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    added = dlg.generate("asce7_lrfd", {"D": [1], "L": [2], "W": [3]})
    names = [c.name for c in project.combinations]
    assert added == len(names)
    assert names[:2] == ["1.4D", "1.2D+1.6L"]
    assert "0.9D-W" in names
    envelope = project.combinations[-1]
    assert envelope.name == ENVELOPE_NAME and envelope.combination_type == "Envelope"
    assert len(envelope.terms) == added - 1
    assert dlg.selected_id() == envelope.id

    vm.undo_stack.undo()
    assert project.combinations == []


@pytest.mark.gui
def test_generator_dialog_offers_every_code_with_its_options(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    gen = CodeGeneratorDialog([c for c in project.analyses if c.type == "Static"])
    qtbot.addWidget(gen)
    assert gen.code() == "asce7_lrfd"
    assert set(CODES) == {"asce7_lrfd", "asce7_asd", "en1990", "tbdy"}
    gen.set_code("en1990")
    assert gen.options()["imposed_category"] == "A"
    gen.set_option("imposed_category", "E")
    gen.set_option("favourable_permanent", True)
    assert gen.options()["imposed_category"] == "E" and gen.options()["favourable_permanent"]
    gen.set_code("tbdy")
    assert gen.options() == {"live_participation": 1.0, "orthogonal": False}
    gen.set_option("live_participation", 0.3)
    assert gen.options()["live_participation"] == 0.3


@pytest.mark.gui
def test_generate_en1990_adds_a_separate_envelope_per_group(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    added = dlg.generate("en1990", {"D": [1], "L": [2], "W": [3]})
    names = [c.name for c in project.combinations]
    assert added == len(names)
    assert "ULS 1.35G+1.5Q" in names and "SLS quasi G+0.3Q" in names
    envelopes = [c.name for c in project.combinations if c.combination_type == "Envelope"]
    assert envelopes == [
        "ULS envelope",
        "SLS characteristic envelope",
        "SLS frequent envelope",
    ]
    vm.undo_stack.undo()
    assert project.combinations == []


@pytest.mark.gui
def test_generate_without_a_dead_case_says_so(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    assert dlg.generate("tbdy", {"L": [2]}) == 0
    assert "needs a Dead case" in dlg.message_text()


@pytest.mark.gui
def test_add_without_a_combinable_case_explains(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    dlg._add_btn.click()
    assert vm.project is not None and vm.project.combinations == []
    assert "Static or Response Spectrum" in dlg.message_text()


@pytest.mark.gui
def test_case_manager_refuses_deleting_a_case_a_combination_uses(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    project.combinations.append(
        LoadCombination(id=1, name="ULS", terms=[CombinationTerm(ref_id=2)])
    )
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: asked.append("q") or QMessageBox.StandardButton.Yes,
    )
    dlg = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dlg)
    dlg._select_by_id(2)
    dlg._on_delete()
    assert [c.id for c in project.analyses] == [1, 2, 3, 4]
    assert "'ULS'" in dlg.message_text()
    assert asked == []

    dlg._select_by_id(3)
    dlg._on_delete()
    assert [c.id for c in project.analyses] == [1, 2, 4]


# ───────────────────── running and displaying ─────────────────────
def _cantilever_window(qtbot, tmp_path):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    target = tmp_path / "cantilever.osmodel"
    shutil.copy(EXAMPLES / "cantilever.osmodel", target)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(target)
    project = window._vm.project
    project.combinations.extend(
        [
            LoadCombination(
                id=1,
                name="ULS",
                terms=[
                    CombinationTerm(ref_id=1, factor=1.2),
                    CombinationTerm(ref_id=2, factor=1.6),
                ],
            ),
            LoadCombination(
                id=2,
                name="ENV",
                combination_type="Envelope",
                terms=[CombinationTerm(ref_id=1), CombinationTerm(ref_id=2)],
            ),
        ]
    )
    return window


@pytest.mark.gui
def test_run_dialog_runs_missing_cases_once_then_combines_from_stored_results(
    qtbot, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("openseespy.opensees")
    from opensees_studio.viewmodels.analysis_runner import IN_PROCESS_ENV
    from opensees_studio.views.dialogs.run_analysis import RunAnalysisDialog

    monkeypatch.delenv(IN_PROCESS_ENV, raising=False)
    window = _cantilever_window(qtbot, tmp_path)
    project = window._vm.project
    dlg = RunAnalysisDialog(window._vm, window._runner, window, case_results=window._case_results)
    qtbot.addWidget(dlg)
    dlg.combinationFinished.connect(window._on_analysis_finished)
    labels = [dlg._case_combo.itemText(i) for i in range(dlg._case_combo.count())]
    assert "Combination: ULS  [Linear Add]" in labels

    finished_cases: list[object] = []
    window._runner.caseFinished.connect(finished_cases.append)
    dlg.select_combination(1)
    with qtbot.waitSignal(dlg.combinationFinished, timeout=120000) as blocker:
        dlg._on_run()
    combo = blocker.args[0]
    assert isinstance(combo, CombinationResults) and combo.single_valued
    assert sorted(r.case_id for r in finished_cases) == [1, 2]  # type: ignore[attr-defined]
    assert window._latest_results is combo
    assert "Combination 'ULS'" in window._results_panel._title.text()

    # The envelope needs the same cases: no second run.
    window._runner.caseFinished.disconnect(finished_cases.append)
    started: list[bool] = []
    window._runner.started.connect(lambda: started.append(True))
    dlg.select_combination(2)
    with qtbot.waitSignal(dlg.combinationFinished, timeout=5000) as blocker:
        dlg._on_run()
    envelope = blocker.args[0]
    assert not envelope.single_valued and started == []
    assert "combining without running" in dlg._log.toPlainText()

    # Display works on the envelope: Max/Min deformed shape, both diagrams.
    assert window._act_show_deformed.isEnabled()
    window._on_show_deformed()
    view = window._post_dock.widget()
    assert view.current_bound() == "max"
    view._bound.setCurrentIndex(1)
    assert view.current_bound() == "min"
    window._on_show_force_diagram()
    data = window._diagram_data(window._post_dock.widget().current_component())
    n_frames = len(project.elements)
    assert len(data.element_ids) == 2 * n_frames

    # Show Results Of switches back to a stored case without running.
    assert window.show_results_of("case:1")
    assert isinstance(window._latest_results, StaticResults)
    assert window.show_results_of("combination:1")
    assert isinstance(window._latest_results, CombinationResults)

    # A model edit makes the stored results stale.
    project.nodes[-1] = project.nodes[-1].model_copy(update={"coords": (6.0, 0.0, 0.0)})
    assert window._case_results.current(project) == {}
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    assert not window.show_results_of("combination:1")


@pytest.mark.gui
def test_envelope_with_a_spectrum_case_draws_both_force_diagrams(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A spectrum case now provides element forces, so its combination has diagrams."""
    import numpy as np

    from opensees_studio.core import ResponseSpectrum, ResponseSpectrumCase
    from opensees_studio.services.element_forces import ForceComponent
    from opensees_studio.services.results import ResponseSpectrumResults

    window = _cantilever_window(qtbot, tmp_path)
    project = window._vm.project
    project.spectra.append(
        ResponseSpectrum(id=1, name="flat", periods=[0.01, 10.0], accelerations=[1.0, 1.0])
    )
    project.analyses.extend(
        [
            ModalCase(id=10, name="Modal", n_modes=2),
            ResponseSpectrumCase(id=11, name="RSX", modal_case_id=10, spectrum_id=1, direction=1),
        ]
    )
    project.combinations.append(
        LoadCombination(
            id=3,
            name="D+E",
            terms=[CombinationTerm(ref_id=1), CombinationTerm(ref_id=11)],
        )
    )
    ndf = project.ndf
    dead = StaticResults(
        case_id=1,
        case_name="DEAD",
        n_steps=1,
        node_disp={n.id: np.zeros((1, ndf)) for n in project.nodes},
        node_reaction={n.id: np.zeros((1, ndf)) for n in project.nodes},
        element_forces={el.id: np.full((1, 12), 2.0) for el in project.elements},
    )
    spectrum = ResponseSpectrumResults(
        case_id=11,
        case_name="RSX",
        direction=1,
        combination="CQC",
        combined_disp={n.id: np.zeros(3) for n in project.nodes},
        node_reaction={n.id: np.ones(ndf) for n in project.nodes},
        element_forces={el.id: np.full(12, 5.0) for el in project.elements},
    )
    window._case_results.put(project, dead)
    window._case_results.put(project, spectrum)
    assert window.show_results_of("combination:3")
    combo = window._latest_results
    assert isinstance(combo, CombinationResults) and not combo.single_valued
    assert combo.missing_fields == []
    window._on_show_force_diagram()
    data = window._diagram_data(ForceComponent.M3)
    assert len(data.element_ids) == 2 * len(project.elements)
    # The upper diagram is dead + peak, the lower dead - peak.
    assert data.abs_max == pytest.approx(7.0)


@pytest.mark.gui
def test_define_menu_opens_the_dialog(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    opened: list[LoadCombinationsDialog] = []

    def fake_exec(self) -> int:  # type: ignore[no-untyped-def]
        opened.append(self)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(LoadCombinationsDialog, "exec", fake_exec)
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    assert window._act_load_combinations.isEnabled()
    window._act_load_combinations.trigger()
    assert len(opened) == 1
    titles = [a.text() for a in window.menuBar().actions()]
    define = window.menuBar().actions()[titles.index("&Define")].menu()
    assert window._act_load_combinations in define.actions()


@pytest.mark.gui
def test_generator_creates_the_missing_load_cases_in_one_undo_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project(dead_case=True)  # 3D, with its DEAD case
    project = vm.project
    assert project is not None
    dead = next(c for c in project.analyses if c.name == "DEAD")
    before = (len(project.time_series), len(project.load_patterns), len(project.analyses))

    gen = CodeGeneratorDialog([c for c in project.analyses if c.type == "Static"], ndm=project.ndm)
    qtbot.addWidget(gen)
    assert gen.create_missing_wanted()
    assert gen.missing_names() == [
        "LIVE",
        "ROOF LIVE",
        "SNOW",
        "RAIN",
        "WIND X",
        "WIND Y",
        "EQ X",
        "EQ Y",
    ]
    gen.set_code("tbdy")
    assert gen.missing_names() == ["LIVE", "WIND X", "WIND Y", "EQ X", "EQ Y"]

    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    added = dlg.generate("asce7_lrfd", {"D": [dead.id]}, create_missing=True)
    created = [c.name for c in project.analyses[before[2] :]]
    assert created == ["LIVE", "ROOF LIVE", "SNOW", "RAIN", "WIND X", "WIND Y", "EQ X", "EQ Y"]
    patterns = {p.name: p for p in project.load_patterns}
    assert all(not patterns[n].nodal_loads and patterns[n].self_weight == 0.0 for n in created)
    names = [c.name for c in project.combinations]
    assert added == len(names) and "1.2D+1.6L+0.5S" in names
    used = {t.ref_id for c in project.combinations for t in c.terms if t.source == "case"}
    assert {c.id for c in project.analyses[before[2] :]} <= used
    assert "Created the load case(s) LIVE, ROOF LIVE" in dlg.message_text()

    vm.undo_stack.undo()
    assert project.combinations == []
    assert (len(project.time_series), len(project.load_patterns), len(project.analyses)) == before


@pytest.mark.gui
def test_generator_in_2d_and_without_any_case_creates_dead_with_self_weight(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    project = vm.project
    assert project is not None
    project.analyses.clear()
    project.load_patterns.clear()
    gen = CodeGeneratorDialog([], ndm=2)
    qtbot.addWidget(gen)
    gen.set_code("tbdy")
    assert gen.missing_names() == ["DEAD", "LIVE", "WIND X", "EQ X"]
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    assert dlg.generate("tbdy", {}, create_missing=True) > 0
    dead = next(p for p in project.load_patterns if p.name == "DEAD")
    assert dead.self_weight == 1.0


@pytest.mark.gui
def test_generator_leaves_cases_alone_when_asked_not_to_create(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    n_cases = len(project.analyses)
    dlg = LoadCombinationsDialog(vm)
    qtbot.addWidget(dlg)
    dlg.generate("asce7_lrfd", {"D": [1], "L": [2]}, create_missing=False)
    assert len(project.analyses) == n_cases
