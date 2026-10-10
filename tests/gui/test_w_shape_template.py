"""W-shape (wide flange) template in the Fiber Section Editor."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import RectangularPatch, StraightLayer, w_shape_patches
from opensees_studio.views.dialogs.section_editor import FiberSectionEditor

COLUMN = {"d": 10.5, "bf": 5.77, "tf": 0.44, "tw": 0.26, "n_web": 15, "n_flange": 16}


def _fill(editor: FiberSectionEditor, **values: float) -> None:
    for name, field in (
        ("d", editor._w_d),
        ("bf", editor._w_bf),
        ("tf", editor._w_tf),
        ("tw", editor._w_tw),
    ):
        field.setValue(values[name])
    editor._w_nfw.setValue(int(values["n_web"]))
    editor._w_nff.setValue(int(values["n_flange"]))


def test_patches_reproduce_the_wf_section_layout() -> None:
    top, web, bottom = w_shape_patches(3, **COLUMN)
    assert (top.n_fib_y, top.n_fib_z, top.y_i, top.y_j) == (16, 1, 4.81, 5.25)
    assert (web.n_fib_y, web.z_i, web.z_j, web.y_i, web.y_j) == (15, -0.13, 0.13, -4.81, 4.81)
    assert (bottom.y_i, bottom.y_j, bottom.z_i, bottom.z_j) == (-5.25, -4.81, -2.885, 2.885)
    assert {p.material_id for p in (top, web, bottom)} == {3}


@pytest.mark.parametrize(
    "bad",
    [{"tf": 5.25}, {"tw": 6.0}, {"d": -1.0}, {"n_web": 0}],
)
def test_impossible_shapes_are_refused(bad: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValueError):
        w_shape_patches(1, **{**COLUMN, **bad})


@pytest.mark.gui
def test_editor_adds_the_three_patches_before_the_layers(qtbot) -> None:  # type: ignore[no-untyped-def]
    editor = FiberSectionEditor([1, 2])
    qtbot.addWidget(editor)
    assert editor._template.currentText() == "W-shape (wide flange)"
    editor._on_add_layer()  # a rebar layer first: the template patches go before it
    editor._w_mat.setCurrentIndex(1)
    _fill(editor, **COLUMN)
    editor._add_template_btn.click()

    section = editor.result_section()
    assert section.patches == w_shape_patches(2, **COLUMN)
    assert all(isinstance(p, RectangularPatch) for p in section.patches)
    assert len(section.layers) == 1 and isinstance(section.layers[0], StraightLayer)
    labels = [editor._item_list.item(i).text() for i in range(editor._item_list.count())]
    assert [label.split("  ")[0] for label in labels] == [
        "W-shape top flange",
        "W-shape web",
        "W-shape bottom flange",
        "Layer",
    ]
    assert "Add patches" not in editor._props_label.text()

    # removing the web removes that patch only
    editor._item_list.setCurrentRow(1)
    editor._on_remove()
    assert [p.n_fib_y for p in editor.result_section().patches] == [16, 16]
    assert len(editor.result_section().layers) == 1


@pytest.mark.gui
def test_editor_shows_why_a_shape_is_refused(qtbot) -> None:  # type: ignore[no-untyped-def]
    editor = FiberSectionEditor([1])
    qtbot.addWidget(editor)
    _fill(editor, **{**COLUMN, "tf": 6.0})
    editor._add_template_btn.click()
    assert "twice the flange thickness" in editor._template_error.text()
    assert editor.result_section().patches == []
