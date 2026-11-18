"""Edit → Delete Loads: by type, by pattern, by selection."""

from __future__ import annotations

from opensees_studio.core import NodalLoad, PlainLoadPattern, PointElementLoad, Project
from opensees_studio.core.load_removal import LOAD_KINDS, Scope, count_loads, remove_loads
from opensees_studio.core.loads import (
    FloorLoad,
    ImposedDisplacement,
    TemperatureLoad,
    TrapezoidalElementLoad,
    UniformElementLoad,
)

ALL = {kind.key for kind in LOAD_KINDS}


def _pattern(pid: int) -> PlainLoadPattern:
    return PlainLoadPattern(
        id=pid,
        time_series_id=1,
        self_weight=1.0,
        nodal_loads=[
            NodalLoad(node_id=1, forces=(1, 0, 0, 0, 0, 0)),
            NodalLoad(node_id=2, forces=(1, 0, 0, 0, 0, 0)),
        ],
        imposed_displacements=[ImposedDisplacement(node_id=1, dof=1, value=0.01)],
        element_loads=[
            UniformElementLoad(element_id=10, wy=-1),
            UniformElementLoad(element_id=11, wy=-1),
        ],
        distributed_loads=[TrapezoidalElementLoad(element_id=10, wy_start=-1, wy_end=-2)],
        point_loads=[PointElementLoad(element_id=11, py=-5)],
        temperature_loads=[TemperatureLoad(element_id=10, alpha=1e-5, uniform=20)],
        floor_loads=[FloorLoad(nodes=(1, 2, 3, 4), value=-3)],
    )


def _project() -> Project:
    return Project(ndm=3, ndf=6, load_patterns=[_pattern(1), _pattern(2)])


def test_counts_on_the_whole_model() -> None:
    counts = count_loads(_project(), ALL, Scope())
    assert counts == {
        "nodal": 4, "imposed": 2, "uniform": 4, "trapezoidal": 2, "point": 2,
        "temperature": 2, "surface": 0, "floor": 2, "self_weight": 2,
    }  # fmt: skip


def test_one_type_one_pattern() -> None:
    project = _project()
    removed = remove_loads(project, {"uniform"}, Scope(pattern_ids=frozenset({2})))
    assert removed == {"uniform": 2}
    assert len(project.load_patterns[0].element_loads) == 2
    assert project.load_patterns[1].element_loads == []
    assert len(project.load_patterns[1].nodal_loads) == 2  # other types untouched


def test_the_selection_decides_through_joints_and_elements() -> None:
    project = _project()
    scope = Scope(node_ids=frozenset({1, 2, 3}), element_ids=frozenset({10}))
    removed = remove_loads(project, ALL, scope)
    assert removed["nodal"] == 4  # nodes 1 and 2, both patterns
    assert removed["uniform"] == 2  # element 10 only
    assert removed["point"] == 0  # the point loads sit on element 11
    assert removed["floor"] == 0  # corner joint 4 is not selected
    assert removed["self_weight"] == 0  # belongs to no joint or element
    assert all(p.self_weight == 1.0 for p in project.load_patterns)
    assert [ul.element_id for ul in project.load_patterns[0].element_loads] == [11]


def test_the_self_weight_is_zeroed_on_the_whole_model() -> None:
    project = _project()
    assert remove_loads(project, {"self_weight"}, Scope()) == {"self_weight": 2}
    assert all(p.self_weight == 0.0 for p in project.load_patterns)
