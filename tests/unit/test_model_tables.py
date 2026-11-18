"""Model tables: rows out of the project, edited rows back into a validated copy."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Group,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
)
from opensees_studio.core.model_tables import apply_tables, model_tables


def _frame(ndm: int = 2, ndf: int = 3) -> Project:
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 3.0), mass=(2.0, 0.0, 2.0, 0.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, Iy=1.0, G=1.0, J=1.0)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="LIVE",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(5.0, 0.0, -1.5, 0.0, 0.0, 0.0))],
            )
        ],
    )


def _rows(project: Project) -> dict[str, list[list[str]]]:
    return {t.name: t.rows for t in model_tables(project)}


def test_a_2d_frame_shows_x_z_and_its_three_dofs() -> None:
    joints, elements, loads = model_tables(_frame())
    assert joints.columns == ("ID", "Name", "X", "Z", "Ux", "Uz", "Ry", "Mx", "Mz", "Iy")
    assert joints.rows[1] == ["2", "", "0", "3", "0", "0", "0", "2", "2", "0"]
    assert elements.rows == [["1", "ElasticBeamColumn", "", "1 2", "1", ""]]
    assert loads.columns == ("Pattern", "Joint", "Fx", "Fz", "My")
    assert loads.rows == [["LIVE", "2", "5", "-1.5", "0"]]


def test_unchanged_rows_give_back_the_same_model() -> None:
    project = _frame(3, 6)
    assert apply_tables(project, _rows(project)) == project


def test_edit_add_and_delete() -> None:
    project = _frame()
    rows = _rows(project)
    rows["Joints"][1][3] = "3.5"  # Z of joint 2
    rows["Joints"].append(["", "top", "4", "3.5", "0", "1", "0", "", "", ""])
    rows["Joint Loads"].append(["1", "3", "0", "-2,5", "0"])  # pattern by id, decimal comma
    edited = apply_tables(project, rows)
    assert edited.node(2).coords == (0.0, 0.0, 3.5)
    assert edited.node(3).coords == (4.0, 0.0, 3.5) and edited.node(3).restraint[2]
    assert [load.node_id for load in edited.load_patterns[0].nodal_loads] == [2, 3]
    assert edited.load_patterns[0].nodal_loads[1].forces[2] == -2.5
    assert project.node(2).coords == (0.0, 0.0, 3.0)  # the original is untouched


def test_element_joints_and_section() -> None:
    project = _frame()
    rows = _rows(project)
    rows["Elements"][0][3] = "2 1"
    edited = apply_tables(project, rows)
    assert edited.element(1).nodes == (2, 1)
    rows["Elements"][0][5] = "1"
    with pytest.raises(ValueError, match="has no material"):
        apply_tables(project, rows)


@pytest.mark.parametrize(
    ("table", "row", "column", "value", "message"),
    [
        ("Joints", 0, 2, "abc", "Joints, row 1, column X"),
        ("Joints", 0, 4, "maybe", "not 1/0"),
        ("Joints", 1, 7, "-1", "a mass is not negative"),
        ("Joints", 1, 0, "1", "appears twice"),
        ("Elements", 0, 3, "1", "has 2 joints"),
        ("Elements", 0, 4, "", "needs a section"),
        ("Joint Loads", 0, 0, "WIND", "no Plain load pattern"),
    ],
)
def test_bad_cells_name_their_place(table, row, column, value, message) -> None:  # type: ignore[no-untyped-def]
    project = _frame()
    rows = _rows(project)
    rows[table][row][column] = value
    with pytest.raises(ValueError, match=message):
        apply_tables(project, rows)


def test_deleting_rows_prunes_groups() -> None:
    project = _frame()
    project.groups.append(Group(id=1, name="all", node_ids=[1, 2], element_ids=[1]))
    rows = _rows(project)
    del rows["Elements"][0]
    del rows["Joints"][0]
    del rows["Joint Loads"][0]
    edited = apply_tables(project, rows)
    assert (edited.groups[0].node_ids, edited.groups[0].element_ids) == ([2], [])


def test_deleting_a_joint_an_element_uses_is_refused() -> None:
    project = _frame()
    rows = _rows(project)
    del rows["Joints"][0]
    with pytest.raises(ValueError, match="missing node 1"):
        apply_tables(project, rows)


def test_editing_a_joint_keeps_its_support_springs() -> None:
    project = _frame()
    project.nodes[1] = project.nodes[1].model_copy(update={"spring": (5.0, 0, 0, 0, 0, 0)})
    rows = _rows(project)
    rows["Joints"][1][3] = "4"
    assert apply_tables(project, rows).node(2).spring == (5.0, 0, 0, 0, 0, 0)
