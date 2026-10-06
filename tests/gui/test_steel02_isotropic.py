"""Published isotropic-hardening inputs survive the material editor."""

import pytest

from opensees_studio.core import Steel02
from opensees_studio.views.dialogs.material_forms import Steel02Form

pytestmark = pytest.mark.gui


def test_steel02_optional_fields_round_trip(qtbot):
    form = Steel02Form()
    qtbot.addWidget(form)
    material = Steel02(id=1, Fy=60, E0=29000, b=0.1, a1=0.05, a2=1, a3=0.05, a4=1, sigInit=2)
    form._populate_specific(material)
    assert form._read_specific(1) == material
    form.show()
    assert all(field.isVisible() for field in form._isotropic.values())
