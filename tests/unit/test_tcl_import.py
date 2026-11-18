"""Reading an OpenSees Tcl script into the typed project.

Each script is the smallest file that shows one rule: the 2D X-Z mapping, a
fibre section, variables/expr/foreach/proc/source, 3D shells, element loads and
what the reader reports when it cannot carry something.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensees_studio.core import (
    Concrete01,
    ElasticBeamColumn,
    ElasticIsotropic,
    ElasticSection,
    FiberSection,
    ShellMITC4Element,
    Steel01,
    UnitSystem,
)
from opensees_studio.services.tcl_import import TclImportError, import_tcl


def _write(tmp_path: Path, text: str, name: str = "model.tcl") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_2d_frame_maps_to_the_xz_plane_and_keeps_the_load(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
model basic -ndm 2 -ndf 3
set L 120.0
node 1 0.0 0.0
node 2 $L 0.0
fix 1 1 1 1
section Elastic 1 29000 10 100
geomTransf Linear 1
element elasticBeamColumn 1 1 2 10 29000 100 1
pattern Plain 1 Linear {
    load 2 0.0 -10.0 0.0
}
""",
    )

    imported = import_tcl(path, units=UnitSystem.US_IN_KIP)

    assert imported.project.ndm == 2
    assert imported.project.ndf == 3
    assert imported.project.meta.units is UnitSystem.US_IN_KIP
    assert [node.coords for node in imported.project.nodes] == [
        (0.0, 0.0, 0.0),
        (120.0, 0.0, 0.0),
    ]
    # TCL 2D DOFs are (Ux, Uy, Rz); the project stores (Ux, Uz, Ry).
    assert imported.project.nodes[0].restraint == (True, False, True, False, True, False)
    load = imported.project.load_patterns[0].nodal_loads[0]
    assert load.forces == (0.0, 0.0, -10.0, 0.0, 0.0, 0.0)

    (element,) = imported.project.elements
    assert isinstance(element, ElasticBeamColumn)
    assert element.nodes == (1, 2)
    assert element.geom_transf == "Linear"
    section = next(s for s in imported.project.sections if s.id == element.section_id)
    assert isinstance(section, ElasticSection)
    assert (section.E, section.A, section.Iz) == (29000.0, 10.0, 100.0)


def test_fibre_section_and_frame_transform(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
model basic -ndm 2 -ndf 3
node 1 0 0
node 2 0 144
fix 1 1 1 1
uniaxialMaterial Concrete01 1 -6.0 -0.004 -5.0 -0.014
uniaxialMaterial Steel01 2 60.0 30000.0 0.01
section Fiber 1 {
    patch rect 1 10 1 -6.0 -7.5 6.0 7.5
    layer straight 2 3 0.6 -6.0 -6.0 -6.0 6.0
}
geomTransf Corotational 1
element dispBeamColumn 1 1 2 5 1 1
""",
    )

    imported = import_tcl(path)

    section = next(s for s in imported.project.sections if s.id == 1)
    assert isinstance(section, FiberSection)
    assert len(section.patches) == 1
    assert len(section.layers) == 1
    material = {material.id: material for material in imported.project.materials}
    assert isinstance(material[1], Concrete01)
    assert isinstance(material[2], Steel01)

    (element,) = imported.project.elements
    assert element.geom_transf == "Corotational"
    assert element.integration_points == 5


def test_variables_expr_foreach_proc_and_source(tmp_path: Path) -> None:
    (tmp_path / "helpers.tcl").write_text(
        """
proc add_node {tag x} {
    node $tag $x 0.0
}
""",
        encoding="utf-8",
    )
    path = _write(
        tmp_path,
        """
model basic -ndm 2 -ndf 2
source helpers.tcl
set spacing 10.0
foreach tag {1 2 3} {
    add_node $tag [expr ($tag - 1) * $spacing]
}
""",
    )

    imported = import_tcl(path)

    assert [node.id for node in imported.project.nodes] == [1, 2, 3]
    assert [node.coords[0] for node in imported.project.nodes] == [0.0, 10.0, 20.0]


def test_3d_shell_keeps_coordinates_and_section(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
model basic -ndm 3 -ndf 6
nDMaterial ElasticIsotropic 1 3000 0.3 0.0
section ElasticMembranePlateSection 1 3000 0.3 0.25 0.0
node 1 0 0 0
node 2 1 0 0
node 3 1 1 0
node 4 0 1 0
element ShellMITC4 1 1 2 3 4 1
""",
    )

    imported = import_tcl(path)

    assert imported.project.ndm == 3
    assert imported.project.ndf == 6
    assert imported.project.nodes[2].coords == (1.0, 1.0, 0.0)
    assert isinstance(imported.project.materials[0], ElasticIsotropic)
    (element,) = imported.project.elements
    assert isinstance(element, ShellMITC4Element)
    assert element.section_id == 1


def test_element_loads_and_their_signs(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
model basic -ndm 2 -ndf 3
node 1 0 0
node 2 10 0
fix 1 1 1 1
section Elastic 1 29000 10 100
geomTransf Linear 1
element elasticBeamColumn 1 1 2 10 29000 100 1
pattern Plain 1 Linear {
    eleLoad -ele 1 -type -beamUniform 0.0 -5.0
    eleLoad -ele 1 -type -beamPoint -3.0 0.25 -1.0
}
""",
    )

    imported = import_tcl(path)

    pattern = imported.project.load_patterns[0]
    (uniform,) = pattern.element_loads
    assert (uniform.wy, uniform.wx) == (0.0, -5.0)
    (point,) = pattern.point_loads
    assert (point.py, point.x, point.px) == (-3.0, 0.25, -1.0)


def test_unsupported_commands_are_reported_not_fatal(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
model basic -ndm 2 -ndf 2
node 1 0 0
uniaxialMaterial BoucWen 1 100 10 1 1 0.1 0.1 0.1
block3D 1 1 1 1 1 stdBrick "1" {
    1 0 0 0
    2 1 0 0
    3 1 1 0
    4 0 1 0
}
analyze 1
someUnknownCommand 1 2 3
""",
    )

    imported = import_tcl(path)

    text = " ".join(imported.notes)
    assert "block3D" in text
    assert "Commands not imported" in text
    assert "Items left out" in text
    assert imported.project.nodes


def test_block2d_mesh_and_quad_signature(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
model basic -ndm 2 -ndf 2
nDMaterial ElasticIsotropic 1 1000 0.25
set thick 2.0
set Quad quad
if {$Quad == "quad"} {
    set eleArgs "$thick PlaneStress 1"
}
block2D 2 1 1 1 $Quad $eleArgs {
    1 0 0
    2 2 0
    3 2 1
    4 0 1
}
""",
    )

    imported = import_tcl(path)

    assert len(imported.project.nodes) == 6
    assert len(imported.project.elements) == 2
    for element in imported.project.elements:
        assert element.thickness == 2.0
        assert element.material_id == 1
        assert element.behaviour == "PlaneStress2D"


def test_a_trailing_wipe_does_not_erase_the_model(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
model basic -ndm 2 -ndf 2
node 1 0 0
node 2 1 0
wipe
""",
    )

    imported = import_tcl(path)

    assert [node.id for node in imported.project.nodes] == [1, 2]


def test_model_without_a_brace_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "model basic -ndm 2 -ndf 2\nnode 1 0 0\nsection Fiber 1 {\n")

    with pytest.raises(TclImportError, match="missing"):
        import_tcl(path)
