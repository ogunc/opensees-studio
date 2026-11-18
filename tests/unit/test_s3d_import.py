"""Reading a PORTICO model (``.s3d``) into a project, scaled to our units.

Each file is written by the test as the smallest model that shows one rule: the
unit factors, the local-axis swap, the releases, the loads, what is left out.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from opensees_studio.core import UnitSystem
from opensees_studio.core.geometry.elements import ElasticBeamColumn
from opensees_studio.core.loads import TrapezoidalElementLoad
from opensees_studio.core.sections import ElasticSection
from opensees_studio.services.s3d_import import (
    S3dImportError,
    import_s3d,
    portico_local_axes,
    read_s3d,
    unit_scale,
)

G = 9.80665


def _node(node_id: int, x: float, y: float, z: float, **extra: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "x": x,
        "y": y,
        "z": z,
        "restraints": {"ux": 0, "uy": 0, "uz": 0, "rx": 0, "ry": 0, "rz": 0},
        "nodeMass": {"mx": 0, "my": 0, "mz": 0},
        "springs": {"kux": 0, "kuy": 0, "kuz": 0, "krx": 0, "kry": 0, "krz": 0},
        **extra,
    }


FIXED = {"ux": 1, "uy": 1, "uz": 1, "rx": 1, "ry": 1, "rz": 1}


def _model(
    *,
    units: str = "kN-m",
    mode: str = "3D",
    end: tuple[float, float, float] = (6.0, 0.0, 0.0),
    releases: list[int] | None = None,
    loads: list[dict[str, Any]] | None = None,
    section: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A cantilever from the origin to ``end``: fixed at node 1, one member."""
    return {
        "version": "1.0",
        "units": units,
        "mode": mode,
        "nodes": [_node(1, 0.0, 0.0, 0.0, restraints=FIXED), _node(2, *end)],
        "elements": [
            {
                "id": 1,
                "n1": 1,
                "n2": 2,
                "matId": 1,
                "secId": 1,
                "releases": releases or [0] * 12,
            }
        ],
        "materials": [{"id": 1, "name": "G30", "E": 2.8e7, "G": 1.2e7, "nu": 0.2, "rho": 2.5}],
        "sections": [
            section
            or {
                "id": 1,
                "name": "B30x50",
                "A": 0.15,
                "Iz": 3.125e-3,
                "Iy": 1.125e-3,
                "J": 2.0e-3,
                "Avy": 0.125,
                "Avz": 0.125,
            }
        ],
        "diaphragms": [],
        "loadCases": [
            {"id": 1, "name": "CM", "type": "static", "selfWeight": False, "loads": loads or []}
        ],
        "combinations": [],
        "grids": {"x": [], "y": [], "z": []},
        **extra,
    }


def _write(tmp_path: Path, data: dict[str, Any], name: str = "model.s3d") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _section(project: Any, element_id: int = 1) -> ElasticSection:
    element = next(e for e in project.elements if e.id == element_id)
    return next(s for s in project.sections if s.id == element.section_id)


# ──────────────────────────── units ────────────────────────────
def test_kn_m_opens_in_si_with_forces_in_newtons(tmp_path: Path) -> None:
    load = {"type": "nodal", "nodeId": 2, "F": [1.0, 0.0, -2.0, 0.0, 3.0, 0.0]}
    result = import_s3d(_write(tmp_path, _model(loads=[load])))
    project = result.project
    assert project.meta.units is UnitSystem.SI_M_N
    assert result.scale.length == 1.0 and result.scale.force == 1000.0
    node = next(n for n in project.nodes if n.id == 2)
    assert node.coords == (6.0, 0.0, 0.0)
    section = _section(project)
    assert pytest.approx(2.8e10) == section.E
    assert pytest.approx(0.15) == section.A
    # 2.5 t/m³ is 2500 kg/m³, which weighs 2500 g N/m³.
    assert section.unit_weight == pytest.approx(2500.0 * G)
    element = project.elements[0]
    assert isinstance(element, ElasticBeamColumn)
    assert element.rho == pytest.approx(2500.0 * 0.15)
    assert element.consistent_mass
    nodal = project.load_patterns[0].nodal_loads[0]
    assert nodal.forces == pytest.approx((1000.0, 0.0, -2000.0, 0.0, 3000.0, 0.0))


def test_a_chosen_target_scales_every_dimension(tmp_path: Path) -> None:
    load = {"type": "dist", "elemId": 1, "w": 10.0, "dir": "gravity"}
    result = import_s3d(_write(tmp_path, _model(loads=[load])), units=UnitSystem.SI_MM_N)
    project = result.project
    node = next(n for n in project.nodes if n.id == 2)
    assert node.coords == pytest.approx((6000.0, 0.0, 0.0))
    section = _section(project)
    assert pytest.approx(2.8e4) == section.E  # kN/m² → N/mm²
    assert pytest.approx(0.15e6) == section.A
    assert section.Iz * section.Iy == pytest.approx(3.125e-3 * 1.125e-3 * 1e24)
    uniform = project.load_patterns[0].element_loads[0]
    assert uniform.wz == pytest.approx(-10.0)  # 10 kN/m is 10 N/mm, downward


def test_us_files_keep_their_numbers_or_scale_pounds_to_kips(tmp_path: Path) -> None:
    kip = import_s3d(_write(tmp_path, _model(units="kip-in"), "kip.s3d"))
    assert kip.project.meta.units is UnitSystem.US_IN_KIP
    assert kip.scale.is_identity
    pounds = import_s3d(_write(tmp_path, _model(units="lb-in"), "lb.s3d"))
    assert pounds.project.meta.units is UnitSystem.US_IN_KIP
    assert pounds.scale.force == pytest.approx(1e-3)
    assert pytest.approx(2.8e4) == _section(pounds.project).E


def test_unit_scale_derived_dimensions() -> None:
    scale = unit_scale("kN-m", UnitSystem.SI_MM_N)
    assert scale.length == pytest.approx(1000.0)
    assert scale.force == pytest.approx(1000.0)
    assert scale.moment == pytest.approx(1e6)
    assert scale.stress == pytest.approx(1e-3)
    # A tonne is 1 N·s²/mm: the coherent mass of the N-mm system.
    assert scale.mass == pytest.approx(1.0)
    assert scale.density == pytest.approx(1e-9)


def test_an_unknown_label_needs_the_units_by_hand(tmp_path: Path) -> None:
    path = _write(tmp_path, _model(units="furlong-stone"))
    with pytest.raises(S3dImportError, match="Unknown PORTICO unit system"):
        import_s3d(path)
    result = import_s3d(path, source_units="kN-m")
    assert result.project.meta.units is UnitSystem.SI_M_N


def test_nodal_mass_and_springs_scale_by_their_own_dimension(tmp_path: Path) -> None:
    data = _model()
    data["nodes"][1]["nodeMass"] = {"mx": 2.0, "my": 0, "mz": 0, "irx": 0, "iry": 0, "irz": 3.0}
    data["nodes"][1]["springs"] = {"kux": 5.0, "kuy": 0, "kuz": 0, "krx": 0, "kry": 0, "krz": 7.0}
    project = import_s3d(_write(tmp_path, data), units=UnitSystem.SI_MM_N).project
    node = next(n for n in project.nodes if n.id == 2)
    assert node.mass[0] == pytest.approx(2.0)  # t
    assert node.mass[5] == pytest.approx(3.0e6)  # t·m² → t·mm²
    assert node.spring[0] == pytest.approx(5.0)  # kN/m → N/mm
    assert node.spring[5] == pytest.approx(7.0e6)  # kN·m/rad → N·mm/rad


# ──────────────────────────── local axes ────────────────────────────
def test_a_3d_beam_swaps_the_bending_axes(tmp_path: Path) -> None:
    """PORTICO's beam has local y up, OpenSees' local z: Iz and Iy trade places."""
    section = {
        "id": 1,
        "name": "B30x50",
        "A": 0.15,
        "Iz": 3.0e-3,
        "Iy": 1.0e-3,
        "J": 2.0e-3,
        "Avy": 0.12,
        "Avz": 0.10,
    }
    imported = _section(import_s3d(_write(tmp_path, _model(section=section))).project)
    assert imported.Iy == pytest.approx(3.0e-3)  # strong axis, about OpenSees' local y
    assert imported.Iz == pytest.approx(1.0e-3)
    assert imported.As2 == pytest.approx(0.10)
    assert imported.As3 == pytest.approx(0.12)
    assert imported.name.endswith("(axes 2-3)")


def test_portico_triads_follow_its_own_rule() -> None:
    import numpy as np

    _, y, z = portico_local_axes(np.zeros(3), np.array([6.0, 0.0, 0.0]))
    assert tuple(y) == pytest.approx((0.0, 0.0, 1.0))
    assert tuple(z) == pytest.approx((0.0, -1.0, 0.0))
    _, y_col, _ = portico_local_axes(np.zeros(3), np.array([0.0, 0.0, 3.0]))
    assert tuple(y_col) == pytest.approx((1.0, 0.0, 0.0))


def test_a_2d_frame_keeps_the_axes(tmp_path: Path) -> None:
    project = import_s3d(_write(tmp_path, _model(mode="2D"))).project
    assert (project.ndm, project.ndf) == (2, 3)
    section = _section(project)
    assert section.Iz == pytest.approx(3.125e-3)
    assert section.Iy is None and section.As3 is None
    assert section.As2 == pytest.approx(0.125)


def test_a_2d_node_off_the_plane_is_refused(tmp_path: Path) -> None:
    data = _model(mode="2D")
    data["nodes"][1]["y"] = 1.0
    with pytest.raises(S3dImportError, match="off the X-Z plane"):
        import_s3d(_write(tmp_path, data))


# ──────────────────────────── releases ────────────────────────────
def test_bending_releases_follow_the_axis_swap(tmp_path: Path) -> None:
    releases = [0] * 12
    releases[11] = 1  # rz at end j: PORTICO's strong-axis moment of a beam
    project = import_s3d(_write(tmp_path, _model(releases=releases))).project
    element = project.elements[0]
    assert element.releases.j.released == ("M2",)
    # OpenSees' Timoshenko beam takes no release: the member loses its shear areas.
    assert not _section(project).has_shear_deformation


def test_2d_releases_are_the_in_plane_moment(tmp_path: Path) -> None:
    releases = [0] * 12
    releases[5] = 1
    releases[4] = 1  # out of plane in 2D: ignored
    project = import_s3d(_write(tmp_path, _model(mode="2D", releases=releases))).project
    assert project.elements[0].releases.i.released == ("M3",)


def test_translational_releases_are_reported(tmp_path: Path) -> None:
    releases = [0] * 12
    releases[6] = 1
    result = import_s3d(_write(tmp_path, _model(releases=releases)))
    assert result.dropped["translational end release"] == 1
    assert not result.project.elements[0].releases.any


def test_end_springs_become_partial_fixity(tmp_path: Path) -> None:
    data = _model(mode="2D", releases=[0, 0, 0, 0, 0, 1] + [0] * 6)
    data["elements"][0]["endSprings"] = {"5": 500.0}
    project = import_s3d(_write(tmp_path, data)).project
    assert project.elements[0].releases.i.spring("M3") == pytest.approx(500_000.0)


# ──────────────────────────── loads ────────────────────────────
def test_gravity_on_a_column_is_axial(tmp_path: Path) -> None:
    load = {"type": "dist", "elemId": 1, "w": 2.0, "dir": "gravity"}
    project = import_s3d(_write(tmp_path, _model(end=(0.0, 0.0, 3.0), loads=[load]))).project
    uniform = project.load_patterns[0].element_loads[0]
    assert uniform.wx == pytest.approx(-2000.0)
    assert uniform.wy == 0.0 and uniform.wz == 0.0


def test_a_local_load_keeps_its_global_direction(tmp_path: Path) -> None:
    """PORTICO localY on a beam points up; in OpenSees that is local z."""
    load = {"type": "dist", "elemId": 1, "w": 4.0, "dir": "localY"}
    project = import_s3d(_write(tmp_path, _model(loads=[load]))).project
    uniform = project.load_patterns[0].element_loads[0]
    assert uniform.wz == pytest.approx(4000.0)
    assert uniform.wy == 0.0


def test_a_trapezoidal_load_drops_shear_deformation(tmp_path: Path) -> None:
    load = {"type": "dist", "elemId": 1, "w": 1.0, "w2": 3.0, "dir": "gravity"}
    result = import_s3d(_write(tmp_path, _model(mode="2D", loads=[load])))
    trapezoid = result.project.load_patterns[0].distributed_loads[0]
    assert isinstance(trapezoid, TrapezoidalElementLoad)
    assert (trapezoid.wy_start, trapezoid.wy_end) == pytest.approx((-1000.0, -3000.0))
    assert not _section(result.project).has_shear_deformation
    assert sum(v for k, v in result.dropped.items() if "shear deformation" in k) == 1


def test_self_weight_and_cases(tmp_path: Path) -> None:
    data = _model()
    data["loadCases"][0]["selfWeight"] = True
    data["loadCases"].append({"id": 2, "name": "SX", "type": "spectrum", "loads": []})
    result = import_s3d(_write(tmp_path, data))
    pattern = result.project.load_patterns[0]
    assert pattern.self_weight == 1.0
    assert [case.name for case in result.project.analyses] == ["CM"]
    assert result.dropped["spectrum load case"] == 1
    # PORTICO's g = 9.80665 is right for kN-m, so nothing to warn about...
    assert not any("Self weight" in note for note in result.notes)
    # ...but a kip-in model weighs differently there than here.
    data["units"] = "kip-in"
    inches = import_s3d(_write(tmp_path, data, "kip.s3d"))
    assert any("g = 386.089" in note for note in inches.notes)


def test_prescribed_displacements_run_in_every_static_case(tmp_path: Path) -> None:
    data = _model(mode="2D", units="kip-in")
    data["nodes"][0]["prescDisp"] = {"ux": 0, "uy": 0, "uz": -0.5, "rx": 0, "ry": 0.01, "rz": 0}
    data["loadCases"].append({"id": 2, "name": "LIVE", "type": "static", "loads": []})
    project = import_s3d(_write(tmp_path, data)).project
    imposed = next(p for p in project.load_patterns if p.imposed_displacements)
    assert [(d.dof, d.value) for d in imposed.imposed_displacements] == [(2, -0.5), (3, 0.01)]
    assert all(imposed.id in case.pattern_ids for case in project.analyses)


def test_combinations_keep_only_imported_cases(tmp_path: Path) -> None:
    data = _model()
    data["loadCases"].append({"id": 2, "name": "SX", "type": "spectrum", "loads": []})
    data["combinations"] = [
        {"id": 1, "name": "1.4CM", "factors": [{"lcId": 1, "factor": 1.4}]},
        {"id": 2, "name": "CM+SX", "factors": [{"lcId": 1, "factor": 1}, {"lcId": 2, "factor": 1}]},
        {"id": 3, "name": "SX", "factors": [{"lcId": 2, "factor": 1}]},
    ]
    result = import_s3d(_write(tmp_path, data))
    combos = {c.name: [(t.ref_id, t.factor) for t in c.terms] for c in result.project.combinations}
    assert combos == {"1.4CM": [(1, 1.4)], "CM+SX": [(1, 1.0)]}
    assert result.dropped["combination term on a case not imported"] == 2
    assert result.dropped["empty combination"] == 1


def test_unsupported_objects_are_counted(tmp_path: Path) -> None:
    data = _model(areas=[{"id": 1, "nodes": [1, 2, 2, 1], "matId": 1, "thickness": 0.2}])
    data["loadCases"][0]["loads"] = [{"type": "temp", "areaId": 1, "dTtop": 10, "dTbot": 0}]
    data["nodes"][1]["springUni"] = {"uz": "c"}
    result = import_s3d(_write(tmp_path, data))
    assert result.dropped["triangular or degenerate area (no 3-node shell)"] == 1
    assert result.dropped["temperature load on an area"] == 1
    assert result.dropped["node springUni"] == 1
    assert "Not imported" in result.summary()


def _plate_model(**extra: Any) -> dict[str, Any]:
    """A 2 x 1 strip of shells on four corner supports, plus the cantilever member."""
    data = _model(**extra)
    data["nodes"] = [
        _node(1, 0.0, 0.0, 0.0, restraints=FIXED),
        _node(2, 6.0, 0.0, 0.0),
        _node(3, 0.0, 1.0, 0.0, restraints=FIXED),
        _node(4, 6.0, 1.0, 0.0),
        _node(5, 3.0, 0.0, 0.0),
        _node(6, 3.0, 1.0, 0.0),
    ]
    data["areas"] = [
        {
            "id": 1,
            "nodes": [1, 5, 6, 3],
            "matId": 1,
            "thickness": 0.2,
            "behavior": "shell",
            "kind": "QUAD",
        },
        {
            "id": 2,
            "nodes": [5, 2, 4, 6],
            "matId": 1,
            "thickness": 0.2,
            "behavior": "plate",
            "kind": "QUAD",
        },
    ]
    return data


def test_quad_areas_become_shells_after_the_members(tmp_path: Path) -> None:
    from opensees_studio.core.geometry.elements import ShellMITC4Element
    from opensees_studio.core.sections import ElasticMembranePlateSection

    result = import_s3d(_write(tmp_path, _plate_model()), units=UnitSystem.SI_MM_N)
    shells = [e for e in result.project.elements if isinstance(e, ShellMITC4Element)]
    assert [e.id for e in shells] == [2, 3]  # after the one frame member
    assert shells[0].nodes == (1, 5, 6, 3)
    plates = [s for s in result.project.sections if isinstance(s, ElasticMembranePlateSection)]
    assert len(plates) == 1  # one material, one thickness
    assert plates[0].h == pytest.approx(200.0)
    assert pytest.approx(2.8e4) == plates[0].E
    assert plates[0].unit_weight == pytest.approx(2.5e-9 * 9806.65)  # t/mm³ times g in mm/s²
    assert any("plate area(s) became full shells" in note for note in result.notes)
    assert "2 shell(s)" in result.summary()


def test_areas_of_a_2d_model_are_reported(tmp_path: Path) -> None:
    data = _model(mode="2D", areas=[{"id": 1, "nodes": [1, 2, 2, 1], "matId": 1, "thickness": 0.2}])
    result = import_s3d(_write(tmp_path, data))
    assert result.dropped["area element (a 2D frame model has no plane elements)"] == 1


def test_a_diaphragm_keeps_its_master_and_spreads_its_mass(tmp_path: Path) -> None:
    data = _plate_model(
        diaphragms=[
            {
                "id": 1,
                "name": "Floor",
                "z": 0.0,
                "nodes": [2, 4, 5, 6],
                "masterId": 5,
                "mass": {"m": 8.0, "Icm": 0},
                "eccentricity": {"ex": 0.1, "ey": 0},
            }
        ]
    )
    result = import_s3d(_write(tmp_path, data))
    diaphragm = result.project.diaphragms[0]
    assert diaphragm.retained_node == 5
    assert diaphragm.constrained_nodes == (2, 4, 6)
    assert diaphragm.perp_dirn == 3
    masses = {n.id: n.mass for n in result.project.nodes}
    # 8 t over four nodes, 2000 kg each, on UX and UY.
    assert masses[4][:3] == pytest.approx((2000.0, 2000.0, 0.0))
    assert result.dropped["diaphragm accidental eccentricity"] == 1
    assert any("spread equally" in note for note in result.notes)


def test_links_become_rigid_links_or_equal_dofs(tmp_path: Path) -> None:
    data = _plate_model(
        links=[
            {"id": 1, "master": 2, "slave": 4, "rigid": True},
            {
                "id": 2,
                "master": 5,
                "slave": 6,
                "rigid": True,
                "dofs": {"ux": 1, "uy": 1, "uz": 1, "rx": 0, "ry": 0, "rz": 0},
            },
            {
                "id": 3,
                "master": 1,
                "slave": 7,
                "rigid": False,
                "dofs": {"ux": 0, "uy": 0, "uz": 1, "rx": 0, "ry": 0, "rz": 0},
            },
        ]
    )
    data["nodes"].append(_node(7, 3.0, 0.5, 1.0))
    project = import_s3d(_write(tmp_path, data)).project
    assert [
        (link.kind, link.retained_node, link.constrained_node) for link in project.rigid_links
    ] == [
        ("beam", 2, 4),
        ("bar", 5, 6),
    ]
    equal = project.mp_constraints[0]
    assert (equal.retained_node, equal.constrained_node, equal.dofs) == (1, 7, (3,))


def test_the_mass_source_follows_portico(tmp_path: Path) -> None:
    data = _model(
        massSource={
            "enabled": True,
            "selfWeight": True,
            "entries": [{"lcId": 1, "factor": 1.0}, {"lcId": 7, "factor": 0.25}],
        }
    )
    result = import_s3d(_write(tmp_path, data))
    source = result.project.mass_source
    assert source is not None
    assert source.element_self_mass
    assert [(p.pattern_id, p.factor) for p in source.patterns] == [(1, 1.0)]
    assert source.include_vertical and not source.lump_at_diaphragms
    assert result.dropped["mass source entry on a case not imported"] == 1
    assert import_s3d(_write(tmp_path, _model(), "plain.s3d")).project.mass_source is None


def test_cables_and_struts_become_one_way_trusses(tmp_path: Path) -> None:
    from opensees_studio.core.geometry.elements import TrussElement
    from opensees_studio.core.materials import ElasticUniaxial

    data = _model(loads=[{"type": "dist", "elemId": 1, "w": 1.0, "dir": "gravity"}])
    data["elements"][0]["cable"] = True
    result = import_s3d(_write(tmp_path, data))
    truss = result.project.elements[0]
    assert isinstance(truss, TrussElement)
    assert truss.area == pytest.approx(0.15)
    material = result.project.materials[0]
    assert isinstance(material, ElasticUniaxial)
    assert (material.E, material.Eneg) == (pytest.approx(2.8e10), 0.0)
    assert result.project.analyses[0].algorithm == "Newton"
    assert result.dropped["distributed load on a tension- or compression-only bar"] == 1
    assert any("go slack" in note for note in result.notes)

    data["elements"][0]["cable"] = False
    data["elements"][0]["compressionOnly"] = True
    strut = import_s3d(_write(tmp_path, data, "strut.s3d")).project.materials[0]
    assert strut.Eneg == pytest.approx(2.8e10)
    assert pytest.approx(2.8e10 * 1e-9) == strut.E


def test_member_temperature_loads_come_with_the_material_alpha(tmp_path: Path) -> None:
    data = _model(loads=[{"type": "temp", "elemId": 1, "dT": 25.0}])
    data["materials"][0]["alpha"] = 1.0e-5
    pattern = import_s3d(_write(tmp_path, data)).project.load_patterns[0]
    thermal = pattern.temperature_loads[0]
    assert (thermal.element_id, thermal.alpha, thermal.uniform) == (1, 1.0e-5, 25.0)
    data["materials"][0]["alpha"] = 0.0
    result = import_s3d(_write(tmp_path, data, "noalpha.s3d"))
    assert result.dropped["temperature load on a material without alpha"] == 1


def test_prescribed_displacements_alone_get_their_own_case(tmp_path: Path) -> None:
    data = _model(mode="2D")
    data["loadCases"] = []
    data["nodes"][1]["prescDisp"] = {"uz": 0.01}
    project = import_s3d(_write(tmp_path, data)).project
    assert [case.name for case in project.analyses] == ["Prescribed displacements"]


def test_grid_lines_are_scaled(tmp_path: Path) -> None:
    data = _model(grids={"x": [0, 6], "y": [], "z": [0, 3.5]})
    project = import_s3d(_write(tmp_path, data), units=UnitSystem.SI_MM_N).project
    grid = project.coord_systems[0].grid
    assert [line.ordinate for line in grid.x_grid_lines] == [0.0, 6000.0]
    assert [line.ordinate for line in grid.z_grid_lines] == [0.0, 3500.0]


# ──────────────────────────── broken files ────────────────────────────
def test_broken_files_are_refused_with_a_reason(tmp_path: Path) -> None:
    bad = tmp_path / "bad.s3d"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(S3dImportError, match="not a readable PORTICO file"):
        read_s3d(bad)
    listed = _write(tmp_path, {"nodes": {"id": 1}}, "listed.s3d")
    with pytest.raises(S3dImportError, match="must be a list"):
        read_s3d(listed)
    data = _model()
    data["elements"][0]["n2"] = 99
    with pytest.raises(S3dImportError, match="missing node 99"):
        import_s3d(_write(tmp_path, data, "ref.s3d"))
    with pytest.raises(S3dImportError, match="No such file"):
        read_s3d(tmp_path / "missing.s3d")


def test_section_used_with_two_materials_becomes_two_sections(tmp_path: Path) -> None:
    data = _model()
    data["nodes"].append(_node(3, 12.0, 0.0, 0.0))
    data["materials"].append({"id": 2, "name": "G40", "E": 3.2e7, "G": 1.3e7, "rho": 2.5})
    data["elements"].append(
        {"id": 2, "n1": 2, "n2": 3, "matId": 2, "secId": 1, "releases": [0] * 12}
    )
    project = import_s3d(_write(tmp_path, data)).project
    names = sorted(s.name for s in project.sections)
    assert len(names) == 2
    assert all(" / G" in name for name in names)
    assert math.isclose(_section(project, 2).E, 3.2e10)
