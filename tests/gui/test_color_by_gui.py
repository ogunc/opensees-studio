"""View → Color By in the viewport: categories, selection on top, the legend."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import ElasticBeamColumn, Node, make_default_section


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=i, coords=(float(i), 0.0, 0.0)) for i in range(1, 4)])
    )
    second = make_default_section(2).model_copy(update={"name": "Other"})
    vm.apply_command(AddSectionsCommand(vm, [make_default_section(1), second]))
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(2, 3), section_id=2),
            ],
        )
    )
    # A clean start: nothing selected, a single colour (whatever an earlier
    # window left behind).
    mw._act_color_none.trigger()
    mw._canvas.selection.clear()
    return mw


def _states(mw) -> np.ndarray:  # type: ignore[no-untyped-def]
    renderer = mw._canvas._renderer
    return np.asarray(renderer._frame_pd.cell_data["_oss_state"])


@pytest.mark.gui
def test_by_section_paints_each_section_and_keeps_the_selection_on_top(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    assert set(_states(mw)) == {0}
    assert getattr(mw._canvas._renderer, "_legend_actor", None) is None

    mw._act_color_section.trigger()

    assert mw._canvas.view_settings.color_by == "section"
    assert mw._act_color_section.isChecked()
    states = _states(mw)
    assert len(set(states)) == 2  # two sections, two colours
    assert mw._canvas._renderer._legend_actor is not None

    mw._canvas.selection.set_selection(set(), {2})
    selected = mw._canvas._renderer._frame_selected
    assert list(_states(mw)) == [states[0], selected]
    mw._canvas.selection.clear()
    assert list(_states(mw)) == list(states)


@pytest.mark.gui
def test_single_colour_removes_the_legend(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._act_color_group.trigger()
    mw._act_color_none.trigger()
    assert mw._canvas.view_settings.color_by == "none"
    assert set(_states(mw)) == {0}
    assert mw._canvas._renderer._legend_actor is None
