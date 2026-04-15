"""Unit tests for material and section parameter forms.

Each form must satisfy a round-trip property: ``form.populate(m); m2 = form.read()``
yields ``m2 == m`` (modulo any None defaults the form's spinbox can't represent).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    Concrete01,
    Concrete02,
    ElasticIsotropic,
    ElasticPP,
    ElasticSection,
    ElasticUniaxial,
    Steel01,
    Steel02,
)


@pytest.mark.gui
def test_steel01_form_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.material_forms import Steel01Form

    original = Steel01(id=7, name="MyS420", Fy=420e6, E0=200e9, b=0.015)
    form = Steel01Form()
    form.populate(original)
    restored = form.read()
    assert restored == original


@pytest.mark.gui
def test_steel02_form_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.material_forms import Steel02Form

    original = Steel02(id=3, name="S355", Fy=355e6, E0=210e9, b=0.005,
                       R0=18.0, cR1=0.925, cR2=0.15)
    form = Steel02Form()
    form.populate(original)
    restored = form.read()
    assert restored == original


@pytest.mark.gui
def test_concrete02_form_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.material_forms import Concrete02Form

    original = Concrete02(
        id=2, name="C30", fpc=-30e6, epsc0=-0.002, fpcu=-15e6, epsU=-0.005,
        ft=3e6, Ets=2e9, **{"lambda": 0.1},
    )
    form = Concrete02Form()
    form.populate(original)
    restored = form.read()
    assert restored == original


@pytest.mark.gui
def test_elastic_isotropic_form_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.material_forms import ElasticIsotropicForm

    original = ElasticIsotropic(id=1, name="Steel", E=200e9, nu=0.3, rho=7850.0)
    form = ElasticIsotropicForm()
    form.populate(original)
    restored = form.read()
    assert restored == original


@pytest.mark.gui
def test_elastic_section_form_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.section_forms import ElasticSectionForm

    original = ElasticSection(
        id=11, name="W14x90",
        E=200e9, A=0.017, Iz=4.16e-4, Iy=1.29e-4, G=80e9, J=2.04e-6,
    )
    form = ElasticSectionForm()
    form.populate(original)
    restored = form.read()
    assert restored == original


@pytest.mark.gui
def test_form_for_dispatches_by_type(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.material_forms import (
        Steel01Form,
        form_for as material_form_for,
    )
    from opensees_studio.views.dialogs.section_forms import (
        ElasticSectionForm,
        form_for as section_form_for,
    )

    s = Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)
    f = material_form_for(s)
    assert isinstance(f, Steel01Form)

    es = ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5)
    f2 = section_form_for(es)
    assert isinstance(f2, ElasticSectionForm)


@pytest.mark.gui
def test_unknown_material_type_raises(qtbot) -> None:  # type: ignore[no-untyped-def]
    """form_for raises KeyError for unsupported types."""
    from opensees_studio.views.dialogs.material_forms import form_for

    class FakeMat:
        type = "Unobtanium"
        id = 1
        name = ""

    with pytest.raises(KeyError):
        form_for(FakeMat())
