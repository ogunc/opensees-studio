"""The shell-contour dock, and the host that paints what it asks for."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticMembranePlateSection,
    Node,
    ShellMITC4Element,
    UnitSystem,
)
from opensees_studio.services.results import StaticResults
from opensees_studio.views.docks.shell_contour import ShellContourView

CORNERS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]


def _window(qtbot, *, with_shell: bool = True):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(mw._vm, [Node(id=i + 1, coords=c) for i, c in enumerate(CORNERS)]),
    )
    mw._vm.apply_command(
        AddSectionsCommand(
            mw._vm,
            [ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2, rho=0.0)],
        ),
    )
    if with_shell:
        mw._vm.apply_command(
            AddElementsCommand(
                mw._vm,
                [ShellMITC4Element(id=20, nodes=(1, 2, 3, 4), section_id=1)],
            ),
        )
    return mw


def _results(n_steps: int = 2) -> StaticResults:
    """Two steps, so the step spinner has something to choose."""
    disp = {node_id: np.zeros((n_steps, 6)) for node_id in (1, 2, 3, 4)}
    disp[3][:, 2] = (0.001, 0.002)
    rows = np.array([[0.0] * 8, [500.0, 0.0, 0.0, 4000.0, -1000.0, 0.0, 0.0, 0.0]])
    return StaticResults(
        case_id=1,
        case_name="contour",
        n_steps=n_steps,
        node_disp=disp,
        element_stresses={20: rows},
    )


# ───────────────────────── the dock on its own ─────────────────────────
@pytest.mark.gui
def test_the_field_picker_lists_every_group(qtbot) -> None:  # type: ignore[no-untyped-def]
    view = ShellContourView(n_steps=3)
    qtbot.addWidget(view)
    labels = [view._field.itemText(i) for i in range(view._field.count())]
    assert any("Deformation" in label for label in labels)
    assert any("Membrane" in label for label in labels)
    assert any("Bending" in label for label in labels)
    assert any("Shear" in label for label in labels)
    assert view._step.maximum() == 3
    assert view._step.value() == 3  # the last step, like every other view


@pytest.mark.gui
def test_directions_are_only_offered_for_principal_fields(qtbot) -> None:  # type: ignore[no-untyped-def]
    view = ShellContourView()
    qtbot.addWidget(view)
    # |u| first: no direction to draw.
    assert view._directions.isEnabled() is False

    index = view._field.findData("N1")
    assert index >= 0
    view._field.setCurrentIndex(index)
    assert view._directions.isEnabled() is True
    view._directions.setChecked(True)
    assert view.directions_wanted() is True

    view._field.setCurrentIndex(view._field.findData("N11"))
    assert view._directions.isEnabled() is False
    assert view.directions_wanted() is False


@pytest.mark.gui
def test_the_scale_is_only_active_for_a_deformation_field(qtbot) -> None:  # type: ignore[no-untyped-def]
    view = ShellContourView()
    qtbot.addWidget(view)
    assert view.current_field() == "umag"
    assert view._scale.isEnabled() is True
    view._field.setCurrentIndex(view._field.findData("M1"))
    assert view._scale.isEnabled() is False
    assert view.current_scale() == 0.0


@pytest.mark.gui
def test_changing_anything_asks_for_a_repaint(qtbot) -> None:  # type: ignore[no-untyped-def]
    view = ShellContourView(n_steps=4)
    qtbot.addWidget(view)
    seen: list[tuple] = []
    view.changed.connect(lambda *args: seen.append(args))

    view._field.setCurrentIndex(view._field.findData("N1"))
    view._step.setValue(2)
    view._directions.setChecked(True)
    assert seen, "no repaint was asked for"
    assert seen[-1][0] == "N1"
    assert seen[-1][1] == 1  # 0-based step, from a 1-based spinner
    assert seen[-1][3] is True


@pytest.mark.gui
def test_a_unit_change_asks_for_a_repaint_of_the_colour_bar(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import UnitConverter

    view = ShellContourView()
    qtbot.addWidget(view)
    calls: list[int] = []
    view.unitsChanged.connect(lambda: calls.append(1))
    view.set_units(UnitConverter(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP))
    assert calls == [1]
    assert view.target_units is UnitSystem.US_IN_KIP


# ───────────────────────── the host ─────────────────────────
@pytest.mark.gui
def test_the_action_is_only_enabled_for_a_static_result_with_shells(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._refresh_action_enablement()
    assert mw._act_shell_contours.isEnabled() is False  # no results yet

    mw._on_analysis_finished(_results())
    mw._refresh_action_enablement()
    assert mw._act_shell_contours.isEnabled() is True

    shell_less = _window(qtbot, with_shell=False)
    shell_less._on_analysis_finished(_results())
    shell_less._refresh_action_enablement()
    assert shell_less._act_shell_contours.isEnabled() is False


@pytest.mark.gui
def test_showing_the_dock_paints_a_contour_and_closing_it_clears_it(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._on_analysis_finished(_results())

    mw._on_show_shell_contours()

    assert mw._post_dock is not None
    assert mw._contour_renderer.is_drawn
    assert mw._contour_renderer.range is not None

    view = mw._post_dock.widget()
    assert isinstance(view, ShellContourView)

    # Picking a resultant repaints with the element's own values.
    view._field.setCurrentIndex(view._field.findData("M11"))
    assert mw._contour_renderer.range == pytest.approx((0.0, 8000.0))  # 4000, padded

    mw._on_back_to_model()
    assert mw._post_dock is None
    assert not mw._contour_renderer.is_drawn


@pytest.mark.gui
def test_the_step_produces_a_different_field(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Step 1 has no moment yet; the last step has 4000."""
    mw = _window(qtbot)
    mw._on_analysis_finished(_results())
    mw._on_show_shell_contours()
    view = mw._post_dock.widget()

    view._field.setCurrentIndex(view._field.findData("M11"))
    assert mw._contour_renderer.range == pytest.approx((0.0, 8000.0))  # 4000, padded

    view._step.setValue(1)  # the first step: no moment at all
    assert mw._contour_renderer.range == pytest.approx((-1.0, 1.0))  # zero, given a band


@pytest.mark.gui
def test_a_display_unit_change_repaints_the_contour(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._on_analysis_finished(_results())
    mw._on_show_shell_contours()

    calls: list[tuple] = []
    original = mw._contour_renderer.render

    def _spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    mw._contour_renderer.render = _spy  # type: ignore[method-assign]
    mw._set_display_units(UnitSystem.US_IN_KIP)

    assert calls, "the contour was not repainted when the units changed"
    _args, kwargs = calls[-1]
    assert kwargs["units"] is UnitSystem.US_IN_KIP
