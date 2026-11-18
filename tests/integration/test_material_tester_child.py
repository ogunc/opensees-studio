"""The Material Tester runs OpenSees in a child analysis CLI (``--material-test``).

OpenSees ends its process on some inputs instead of raising, so the GUI never
calls it in its own process: a dead child must come back as an error message,
and a child that finishes must return what the in-process service returns.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("openseespy")

from opensees_studio import child_cli
from opensees_studio.core import ElasticIsotropic, ElasticUniaxial, Project, Steel02
from opensees_studio.services import material_tester
from opensees_studio.services.material_tester import (
    test_uniaxial_material,
    test_uniaxial_material_in_child,
)
from opensees_studio.viewmodels.material_tester_vm import MaterialTesterViewModel, cyclic_protocol


@pytest.fixture(autouse=True)
def _child_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(child_cli.IN_PROCESS_ENV, raising=False)


def test_child_result_equals_the_in_process_result() -> None:
    steel = Steel02(id=3, Fy=420e6, E0=200e9, b=0.01, name="S")
    protocol = cyclic_protocol(0.01, 2, 40)
    support = [ElasticUniaxial(id=1, E=1.0), steel]
    direct = test_uniaxial_material(steel, protocol, support=support)
    child = test_uniaxial_material_in_child(steel, protocol, support=support)
    # Floats travel as JSON, which round-trips a double exactly.
    assert child == direct


def test_child_error_keeps_its_type_and_message() -> None:
    with pytest.raises(TypeError, match="nD material"):
        test_uniaxial_material_in_child(
            ElasticIsotropic(id=1, E=30e9, nu=0.2), cyclic_protocol(0.01, 1, 10)
        )


def test_a_dead_child_is_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    code = "import os, sys; sys.stderr.write('native solver message\\n'); os._exit(255)"
    monkeypatch.setattr(child_cli, "analysis_cli_command", lambda: [sys.executable, "-c", code])
    with pytest.raises(RuntimeError, match="exit code 255") as info:
        test_uniaxial_material_in_child(ElasticUniaxial(id=1, E=1.0), cyclic_protocol(0.01, 1, 10))
    assert "native solver message" in str(info.value)


def test_view_model_reports_a_dead_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        child_cli,
        "analysis_cli_command",
        lambda: [sys.executable, "-c", "import os; os._exit(3221225477)"],
    )
    vm = MaterialTesterViewModel(Project(materials=[ElasticUniaxial(id=1, E=1.0)]))
    assert not vm.run()
    assert vm.error is not None and vm.error.startswith("RuntimeError: OpenSees ended the process")
    assert vm.strain.size == 0


def test_view_model_runs_in_process_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_child(*args: object, **kwargs: object) -> None:
        raise AssertionError("the child path ran")

    monkeypatch.setenv(child_cli.IN_PROCESS_ENV, "1")
    monkeypatch.setattr(material_tester, "test_uniaxial_material_in_child", no_child)
    monkeypatch.setattr(
        "opensees_studio.viewmodels.material_tester_vm.test_uniaxial_material_in_child", no_child
    )
    vm = MaterialTesterViewModel(Project(materials=[ElasticUniaxial(id=1, E=200e9)]))
    assert vm.run(), vm.error
    assert vm.stress.size > 0
