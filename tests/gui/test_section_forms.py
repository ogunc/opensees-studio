"""Regression: clicking a FiberSection / SectionAggregator row in the
Section Library must not crash ``form_for`` with KeyError."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    AggregatorDOF,
    ElasticSection,
    FiberSection,
    RectangularPatch,
    SectionAggregator,
)
from opensees_studio.views.dialogs.section_forms import (  # noqa: E402
    FORM_REGISTRY,
    form_for,
)


def test_fiber_section_has_registered_form() -> None:
    assert "FiberSection" in FORM_REGISTRY


def test_section_aggregator_has_registered_form() -> None:
    assert "SectionAggregator" in FORM_REGISTRY


@pytest.mark.gui
def test_form_for_elastic_section_returns_editable_form(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = ElasticSection(
        id=1, name="Rect", E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6,
    )
    f = form_for(s)
    qtbot.addWidget(f)
    assert f.type_label == "Elastic Section"


@pytest.mark.gui
def test_form_for_fiber_section_returns_summary(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = FiberSection(
        id=1, name="RC",
        patches=[RectangularPatch(
            material_id=1, n_fib_y=4, n_fib_z=4,
            y_i=-0.1, z_i=-0.15, y_j=0.1, z_j=0.15,
        )],
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
        id=2, name="Agg", section_id=1,
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
