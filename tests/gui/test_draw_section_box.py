"""The Section box of the Tools toolbar: shown while Draw Frame is armed, feeds its frames."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    yield mw
    mw._help_controller.uninstall()


def test_the_box_lists_frame_sections_only_while_drawing_frames(window) -> None:
    from opensees_studio.commands import AddSectionsCommand
    from opensees_studio.core import ElasticMembranePlateSection, ElasticSection

    window._vm.apply_command(
        AddSectionsCommand(
            window._vm,
            [
                ElasticSection(
                    id=1, name="W10X12", E=2e11, A=0.002, Iz=1e-6, Iy=2e-5, G=8e10, J=2e-8
                ),
                ElasticSection(
                    id=2, name="W14X30", E=2e11, A=0.006, Iz=8e-6, Iy=1e-4, G=8e10, J=1e-7
                ),
                ElasticMembranePlateSection(id=3, name="Slab", E=3e10, nu=0.2, h=0.2),
            ],
        )
    )
    assert not window._draw_section_action.isVisible()
    window._act_tool_draw_frame.trigger()
    combo = window._draw_section_combo
    assert window._draw_section_action.isVisible()
    assert [combo.itemText(i) for i in range(combo.count())] == ["W10X12", "W14X30"]
    combo.setCurrentIndex(1)
    assert window._draw_frame_tool.section_id == 2

    window._act_tool_select.trigger()
    assert not window._draw_section_action.isVisible()
    window._act_tool_draw_frame.trigger()
    assert window._draw_frame_tool.section_id == 2  # the choice is kept


def test_a_project_without_sections_draws_with_the_default(window) -> None:
    window._act_tool_draw_frame.trigger()
    combo = window._draw_section_combo
    assert combo.count() == 1
    assert combo.currentData() is None
    assert window._draw_frame_tool.section_id is None
