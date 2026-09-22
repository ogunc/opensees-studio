"""Material Tester view model against the real openseespy solver.

These cases would be unit tests by intent (Qt-free, fast) but they invoke
openseespy, so they live here per the CLAUDE.md test split, like
``test_material_tester.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import ElasticUniaxial, Project, Steel02
from opensees_studio.viewmodels.material_tester_vm import MaterialTesterViewModel, strain_history


def _vm(material) -> MaterialTesterViewModel:
    return MaterialTesterViewModel(Project(materials=[material]))


@pytest.mark.parametrize("kind", ["monotonic", "cyclic", "increasing"])
def test_elastic_stress_equals_e_times_strain(kind: str) -> None:
    vm = _vm(ElasticUniaxial(id=1, E=200e9))
    vm.protocol_kind = kind  # type: ignore[assignment]
    vm.steps_per_half_cycle = 20
    assert vm.run(), vm.error
    np.testing.assert_allclose(vm.stress, 200e9 * vm.strain, rtol=1e-9, atol=1e-3)
    # The service records exactly the strain history the generator predicts.
    np.testing.assert_allclose(vm.strain, strain_history(vm.build_protocol()), atol=1e-12)


def test_steel02_closed_loop_positive_energy() -> None:
    fy, e0 = 420e6, 200e9
    vm = _vm(Steel02(id=1, Fy=fy, E0=e0, b=0.01))
    vm.protocol_kind = "cyclic"
    vm.amplitude = 0.01
    vm.n_cycles = 2
    vm.steps_per_half_cycle = 100
    assert vm.run(), vm.error
    assert vm.strain.size == 2 * 3 * 100
    # Each cycle closes on the strain axis where it started.
    assert vm.strain[299] == pytest.approx(0.0, abs=1e-12)
    assert vm.strain[-1] == pytest.approx(0.0, abs=1e-12)
    d = vm.derived
    assert d is not None
    assert len(d.energy_per_cycle) == 2
    assert all(e > 0.0 for e in d.energy_per_cycle)
    # Bounded by the rigid-plastic rectangle 4 * sigma_max * amplitude.
    sig_max = float(np.abs(vm.stress).max())
    assert d.energy_per_cycle[1] < 4.0 * sig_max * vm.amplitude
    # Stable second cycle dissipates a sizeable share of that bound.
    assert d.energy_per_cycle[1] > 0.5 * 4.0 * fy * (vm.amplitude - fy / e0)
    assert abs(d.peak_stress) > fy
