"""Nonprismatic sections: interpolation, subdivision and refresh."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    FiberSection,
    LinearTimeSeries,
    Node,
    NonprismaticSection,
    NonprismaticSegment,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    RectShape,
    TemperatureLoad,
    TrapezoidalElementLoad,
    UniformElementLoad,
)
from opensees_studio.services.nonprismatic import (
    materialize_nonprismatic,
    refresh_nonprismatic,
    section_at,
)


def _section(section_id: int, depth: float, width: float = 1.0) -> ElasticSection:
    return ElasticSection(
        id=section_id,
        name=f"S{section_id}",
        E=200e9,
        A=depth * width,
        Iz=depth * width**3 / 12,
        Iy=width * depth**3 / 12,
        G=80e9,
        J=1e-6,
        shape=RectShape(d=depth, b=width),
    )


def _template(start: ElasticSection, end: ElasticSection) -> NonprismaticSection:
    return NonprismaticSection(
        id=3,
        name="Taper",
        segments=[
            NonprismaticSegment(
                start_section_id=start.id,
                end_section_id=end.id,
                length_type="relative",
                length=1.0,
            )
        ],
    )


def _project(
    with_loads: bool = False,
    start: ElasticSection | None = None,
    end: ElasticSection | None = None,
    template: NonprismaticSection | None = None,
) -> tuple[Project, NonprismaticSection]:
    start = start or _section(1, 2.0)
    end = end or _section(2, 4.0)
    template = template or _template(start, end)
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
        Node(id=2, coords=(10.0, 0.0, 0.0)),
    ]
    patterns = []
    if with_loads:
        patterns = [
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-1.0)],
                distributed_loads=[
                    TrapezoidalElementLoad(
                        element_id=1,
                        x_start=0.25,
                        x_end=0.75,
                        wy_start=-1.0,
                        wy_end=-3.0,
                    )
                ],
                point_loads=[PointElementLoad(element_id=1, x=0.4, pz=-5.0)],
                temperature_loads=[TemperatureLoad(element_id=1, alpha=1e-5, uniform=10.0)],
            )
        ]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[start, end, template],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=template.id)],
        time_series=[LinearTimeSeries(id=1, name="Linear")] if with_loads else [],
        load_patterns=patterns,
    )
    project.validate_references()
    return project, template


def test_fractions_normalise_relative_and_mix_absolute() -> None:
    relative = NonprismaticSection(
        id=1,
        segments=[
            NonprismaticSegment(start_section_id=1, end_section_id=1, length=1),
            NonprismaticSegment(start_section_id=1, end_section_id=1, length=3),
        ],
    )
    assert relative.fractions() == pytest.approx([0.25, 0.75])

    mixed = NonprismaticSection(
        id=2,
        segments=[
            NonprismaticSegment(
                start_section_id=1, end_section_id=1, length_type="relative", length=0.5
            ),
            NonprismaticSegment(
                start_section_id=1, end_section_id=1, length_type="absolute", length=5
            ),
            NonprismaticSegment(
                start_section_id=1, end_section_id=1, length_type="absolute", length=5
            ),
        ],
    )
    assert mixed.fractions() == pytest.approx([0.5, 0.25, 0.25])


def test_section_at_interpolates_the_drawn_shape() -> None:
    project, template = _project()
    middle = section_at(project, template, 0.5)
    # Depth 2 -> 4 at midspan, width 1: A = 3, Iz = 3/12, Iy = 27/12.
    assert pytest.approx(3.0) == middle.A
    assert middle.Iz == pytest.approx(3.0 / 12.0)
    assert middle.Iy == pytest.approx(27.0 / 12.0)
    assert isinstance(middle.shape, RectShape)
    assert middle.shape.d == pytest.approx(3.0)


def test_materialize_subdivides_and_splits_every_kind_of_load() -> None:
    project, template = _project(with_loads=True)
    report = materialize_nonprismatic(project)

    assert report.members == 1
    assert report.elements == 12
    assert report.nodes == 11
    assert report.subdivisions[template.id] == 12
    assert len(project.nodes) == 13
    assert len(project.elements) == 12
    assert [el.id for el in project.elements] == list(range(1, 13))
    assert project.elements[0].nodes == (1, 3)
    assert project.elements[-1].nodes == (13, 2)
    assert any(
        group.name == f"Nonprismatic section {template.id} member 1" for group in project.groups
    )

    pattern = project.load_patterns[0]
    assert len(pattern.element_loads) == 12
    assert all(load.wy == pytest.approx(-1.0) for load in pattern.element_loads)

    # The 0.25-0.75 trapezoid crosses pieces 3 through 8.
    assert len(pattern.distributed_loads) == 6
    assert pattern.distributed_loads[0].x_start == pytest.approx(0.0)
    assert pattern.distributed_loads[-1].x_end == pytest.approx(1.0)
    assert pattern.distributed_loads[0].wy_start == pytest.approx(-1.0)
    assert pattern.distributed_loads[-1].wy_end == pytest.approx(-3.0)

    assert len(pattern.point_loads) == 1
    assert pattern.point_loads[0].element_id == project.elements[4].id
    assert pattern.point_loads[0].x == pytest.approx(0.8)

    assert len(pattern.temperature_loads) == 12
    assert all(load.uniform == pytest.approx(10.0) for load in pattern.temperature_loads)
    project.validate_references()


def test_a_point_load_drops_shear_areas_the_timoshenko_runner_cannot_take() -> None:
    start = _section(1, 2.0).model_copy(update={"As2": 1.0, "As3": 1.0})
    end = _section(2, 4.0).model_copy(update={"As2": 1.0, "As3": 1.0})
    project, _ = _project(start=start, end=end, with_loads=True)
    materialize_nonprismatic(project)
    pieces = [
        section
        for section in project.sections
        if isinstance(section, ElasticSection) and section.id not in (1, 2)
    ]
    assert pieces
    assert all(piece.As2 is None and piece.As3 is None for piece in pieces)


def test_refresh_reinterpolates_pieces_without_changing_topology() -> None:
    project, template = _project()
    materialize_nonprismatic(project)
    before = {el.id: el.section_id for el in project.elements}
    revised = template.model_copy(
        update={
            "segments": [
                NonprismaticSegment(
                    start_section_id=1,
                    end_section_id=2,
                    length_type="relative",
                    length=1.0,
                    variation="cubic",
                )
            ]
        }
    )
    project.sections[2] = revised
    report = refresh_nonprismatic(project, revised)

    assert report.members == 1
    assert report.elements == 12
    assert report.stale_counts == 0
    assert len(project.nodes) == 13
    assert len(project.elements) == 12
    assert any(before[el.id] != el.section_id for el in project.elements)


def test_a_2d_nonprismatic_section_does_not_need_iy() -> None:
    start = ElasticSection(
        id=1, name="Small", E=200e9, A=2.0, Iz=0.6667, shape=RectShape(d=2.0, b=1.0)
    )
    end = ElasticSection(id=2, name="Big", E=200e9, A=4.0, Iz=5.3333, shape=RectShape(d=4.0, b=1.0))
    template = NonprismaticSection(
        id=3,
        segments=[NonprismaticSegment(start_section_id=1, end_section_id=2, length=1.0)],
    )
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(10.0, 0.0, 0.0)),
        ],
        sections=[start, end, template],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=3)],
    )
    project.validate_references()
    middle = section_at(project, template, 0.5)
    assert pytest.approx(3.0) == middle.A
    assert middle.Iz == pytest.approx(27.0 / 12.0)  # b*d^3/12 in the 2D convention
    assert middle.Iy is None
    report = materialize_nonprismatic(project)
    assert report.elements == 12
    assert all(piece.Iy is None for piece in project.sections if isinstance(piece, ElasticSection))


def test_a_nonprismatic_section_requires_elastic_segments() -> None:
    elastic = _section(1, 2.0)
    fibre = FiberSection(id=2, name="Fiber")
    template = NonprismaticSection(
        id=3,
        segments=[NonprismaticSegment(start_section_id=1, end_section_id=2, length=1.0)],
    )
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
        ],
        sections=[elastic, fibre, template],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=3)],
    )
    with pytest.raises(ValueError, match="must use ElasticSection"):
        project.validate_references()


def test_a_mixed_relative_and_absolute_definition_cannot_overflow() -> None:
    with pytest.raises(ValueError, match="less than 1"):
        NonprismaticSection(
            id=1,
            segments=[
                NonprismaticSegment(
                    start_section_id=1,
                    end_section_id=1,
                    length_type="relative",
                    length=1.0,
                ),
                NonprismaticSegment(
                    start_section_id=1,
                    end_section_id=1,
                    length_type="absolute",
                    length=1.0,
                ),
            ],
        )
