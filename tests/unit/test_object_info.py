"""core.object_info: the Location / Assignments / Loads tabs of a joint and an element."""

from __future__ import annotations

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    ProjectMeta,
    TrapezoidalElementLoad,
    UniformElementLoad,
    UnitSystem,
)
from opensees_studio.core.groups import Group
from opensees_studio.core.object_info import element_info, node_info


def _project() -> Project:
    return Project(
        meta=ProjectMeta(units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=1,
                name="A",
                coords=(0.0, 0.0, 0.0),
                restraint=(True, False, True, False, False, False),
            ),
            Node(id=2, coords=(6.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, name="W14X30", E=200e9, A=5.7e-3, Iz=1.21e-4)],
        elements=[ElasticBeamColumn(id=1, name="Beam", nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="DEAD",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-10e3)],
                nodal_loads=[NodalLoad(node_id=2, forces=(5e3, 0, 0, 0, 2e3, 0))],
            ),
            PlainLoadPattern(
                id=2,
                name="LIVE",
                time_series_id=1,
                point_loads=[PointElementLoad(element_id=1, py=-50e3, x=0.25)],
                distributed_loads=[
                    TrapezoidalElementLoad(element_id=1, wy_start=0.0, wy_end=-15e3)
                ],
            ),
        ],
        groups=[Group(id=1, name="Girders", element_ids=[1])],
    )


def _rows(info, title: str) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    tab = next(t for t in info.tabs if t.title == title)
    rows: dict[str, list[str]] = {}
    for label, value in tab.rows:
        rows.setdefault(label, []).append(value)
    return rows


def test_a_joint_says_where_it_is_what_restrains_it_and_what_loads_it() -> None:
    support = node_info(_project(), 1)
    assert support is not None
    assert support.title == "Joint 1"
    assert [t.title for t in support.tabs] == ["Location", "Assignments", "Loads"]
    assert _rows(support, "Location")["Coordinates"] == ["(0, 0) m"]
    assert _rows(support, "Location")["Connected elements"] == ["1 (ElasticBeamColumn)"]
    assert _rows(support, "Assignments")["Restraints"] == ["Ux, Uz"]
    assert _rows(support, "Loads") == {"Loads": ["none"]}

    loaded = node_info(_project(), 2)
    assert loaded is not None
    assert _rows(loaded, "Assignments")["Restraints"] == ["none (free)"]
    assert _rows(loaded, "Loads")["DEAD"] == ["Joint load: Fx 5 kN; My 2000 N·m"]


def test_an_element_lists_every_load_with_its_value_and_place() -> None:
    info = element_info(_project(), 1)
    assert info is not None
    assert info.title == "ElasticBeamColumn 1"
    location = _rows(info, "Location")
    assert location["Length"] == ["6 m"]
    assert location["Joint j"] == ["2  (6, 0) m"]
    assert location["Local x"] == ["(1.0000, 0.0000, 0.0000)"]
    assert location["Local y"] == ["(0.0000, 0.0000, 1.0000)"]
    assignments = _rows(info, "Assignments")
    assert assignments["Section"] == ["1: W14X30"]
    assert assignments["Releases, end i"] == ["none"]
    assert assignments["Groups"] == ["Girders"]
    loads = _rows(info, "Loads")
    assert loads["DEAD"] == ["Uniform, local: wy -10 kN/m"]
    assert loads["LIVE"] == [
        "Point, local: py -50 kN at x/L = 0.25 (1.5 m from end i)",
        "Distributed, local: wy 0 to -15 kN/m from x/L = 0 to 1",
    ]


def test_values_follow_the_display_units_and_a_missing_object_is_none() -> None:
    project = _project()
    project.meta.display_units = UnitSystem.SI_MM_N
    info = element_info(project, 1)
    assert info is not None
    assert _rows(info, "Location")["Length"] == ["6000 mm"]
    assert _rows(info, "Loads")["DEAD"] == ["Uniform, local: wy -10 N/mm"]
    assert node_info(project, 99) is None
    assert element_info(project, 99) is None
