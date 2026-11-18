"""Regression: clicking a FiberSection / SectionAggregator row in the
Section Library must not crash ``form_for`` with KeyError."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (
    AggregatorDOF,
    ElasticMembranePlateSection,
    ElasticSection,
    FiberSection,
    NonprismaticSection,
    NonprismaticSegment,
    Project,
    RectangularPatch,
    SectionAggregator,
)
from opensees_studio.views.dialogs.section_forms import (
    FORM_REGISTRY,
    form_for,
)


def test_fiber_section_has_registered_form() -> None:
    assert "FiberSection" in FORM_REGISTRY


def test_section_aggregator_has_registered_form() -> None:
    assert "SectionAggregator" in FORM_REGISTRY


def test_plate_section_has_registered_form() -> None:
    assert "ElasticMembranePlateSection" in FORM_REGISTRY


@pytest.mark.gui
def test_form_for_plate_section_round_trips(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = ElasticMembranePlateSection(id=3, name="Slab", E=30e9, nu=0.2, h=0.25, rho=2500.0)
    f = form_for(s)
    qtbot.addWidget(f)
    assert f.type_label == "Plate Section (shell)"
    f.populate(s)
    assert f.read() == s


@pytest.mark.gui
def test_form_for_elastic_section_returns_editable_form(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = ElasticSection(
        id=1,
        name="Rect",
        E=200e9,
        A=0.01,
        Iz=1e-5,
        Iy=1e-5,
        G=80e9,
        J=1e-6,
    )
    f = form_for(s)
    qtbot.addWidget(f)
    assert f.type_label == "Elastic Section"


@pytest.mark.gui
def test_nonprismatic_form_round_trips(qtbot) -> None:  # type: ignore[no-untyped-def]
    a = ElasticSection(id=1, name="Small", E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)
    b = ElasticSection(id=2, name="Big", E=200e9, A=0.02, Iz=2e-5, Iy=2e-5, G=80e9, J=2e-6)
    taper = NonprismaticSection(
        id=3,
        name="Taper",
        segments=[
            NonprismaticSegment(
                start_section_id=1,
                end_section_id=2,
                length_type="relative",
                length=1.0,
                variation="parabolic",
            )
        ],
        subdivisions=24,
    )
    project = Project(nodes=[], sections=[a, b, taper], elements=[])
    form = form_for(taper, project)
    qtbot.addWidget(form)
    assert form.type_label == "Nonprismatic Section"
    assert form._subdivisions.value() == 24
    assert form._table.rowCount() == 1
    assert form.read() == taper


@pytest.mark.gui
def test_a_new_nonprismatic_form_starts_with_one_segment(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.section_forms import make_form

    a = ElasticSection(id=1, name="A", E=200e9, A=0.01, Iz=1e-5)
    project = Project(nodes=[], sections=[a], elements=[])
    form = make_form(FORM_REGISTRY["NonprismaticSection"], project)
    qtbot.addWidget(form)
    form._section_id = 2
    assert form._table.rowCount() == 1
    section = form.read()
    assert section.id == 2
    assert section.segments[0].start_section_id == 1
    assert section.segments[0].end_section_id == 1


@pytest.mark.gui
def test_nonprismatic_form_can_add_and_remove_segments(qtbot) -> None:  # type: ignore[no-untyped-def]
    a = ElasticSection(id=1, name="A", E=200e9, A=0.01, Iz=1e-5)
    taper = NonprismaticSection(
        id=2,
        segments=[NonprismaticSegment(start_section_id=1, end_section_id=1, length=1.0)],
    )
    form = form_for(taper, Project(nodes=[], sections=[a, taper], elements=[]))
    qtbot.addWidget(form)
    form._on_add_row()
    assert form._table.rowCount() == 2
    form._table.setCurrentCell(1, 0)
    form._on_remove_row()
    assert form._table.rowCount() == 1


@pytest.mark.gui
def test_form_for_fiber_section_returns_summary(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = FiberSection(
        id=1,
        name="RC",
        patches=[
            RectangularPatch(
                material_id=1,
                n_fib_y=4,
                n_fib_z=4,
                y_i=-0.1,
                z_i=-0.15,
                y_j=0.1,
                z_j=0.15,
            )
        ],
    )
    f = form_for(s)
    qtbot.addWidget(f)
    assert f.type_label == "Fiber Section"
    # read() round-trips without crashing.
    out = f.read(1)
    assert isinstance(out, FiberSection)
    assert len(out.patches) == 1


@pytest.mark.gui
def test_form_for_section_aggregator_returns_summary(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SectionAggregator(
        id=2,
        name="Agg",
        section_id=1,
        pairings=[AggregatorDOF(material_id=3, dof="T")],
    )
    f = form_for(s)
    qtbot.addWidget(f)
    assert f.type_label == "Section Aggregator"


@pytest.mark.gui
def test_form_for_unknown_type_falls_back(qtbot) -> None:  # type: ignore[no-untyped-def]
    """An unknown section type must NOT raise — the dialog gets a
    placeholder form so the whole UI doesn't go down."""

    class _Mystery:
        type = "NotRegistered"
        id = 99
        name = "???"

    f = form_for(_Mystery())
    qtbot.addWidget(f)
    # Placeholder form exists; no exception raised.
    assert f is not None
