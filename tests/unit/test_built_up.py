"""Built-up I-shapes: properties from the plates, the built-up rules of AISC 360, saved settings."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from opensees_studio.core import Project
from opensees_studio.core.design.aisc360 import (
    IShape,
    Steel,
    flexure_major,
    shear_major,
    slenderness,
)
from opensees_studio.core.design.built_up import analysis_section, built_up_ishape
from opensees_studio.core.design.built_up_model import BuiltUpShape
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.services import load_project, save_project

STEEL = Steel(Fy=50.0, E=29000.0, G=11200.0)
GIRDER = BuiltUpShape(name="PG1", d=36.0, bf=12.0, tf=1.0, tw=0.5)


def test_properties_come_from_the_plates() -> None:
    s = built_up_ishape(GIRDER)
    assert pytest.approx(2 * 12 * 1 + 34 * 0.5) == s.A
    assert s.Ix == pytest.approx((12 * 36**3 - 11.5 * 34**3) / 12)
    assert s.Iy == pytest.approx((2 * 1 * 12**3 + 34 * 0.5**3) / 12)
    assert s.Zx == pytest.approx(12 * 1 * 35 + 0.5 * 34**2 / 4)
    assert s.Sx == pytest.approx(s.Ix / 18)
    assert pytest.approx((2 * 12 * 1 + 35 * 0.5**3) / 3) == s.J
    assert s.Cw == pytest.approx(s.Iy * 35**2 / 4)
    assert s.h == pytest.approx(34.0)


def test_impossible_plates_are_refused() -> None:
    with pytest.raises(ValueError, match="whole depth"):
        BuiltUpShape(name="X", d=2.0, bf=12.0, tf=1.0, tw=0.5)
    with pytest.raises(ValueError, match="web"):
        BuiltUpShape(name="X", d=36.0, bf=0.4, tf=1.0, tw=0.5)


def test_built_up_flange_limits_take_kc() -> None:
    built = built_up_ishape(GIRDER)
    rolled = IShape(**{k: getattr(built, k) for k in IShape.__dataclass_fields__})
    kc = 4 / math.sqrt(34 / 0.5)
    b = slenderness(built, STEEL)
    r = slenderness(rolled, STEEL)
    assert built.kc == pytest.approx(kc)
    assert b.flange_compression_limit == pytest.approx(0.64 * math.sqrt(kc * 29000 / 50))
    assert b.flange_noncompact == pytest.approx(0.95 * math.sqrt(kc * 29000 / 35))
    assert r.flange_compression_limit == pytest.approx(0.56 * math.sqrt(29000 / 50))
    assert b.flange_compact == r.flange_compact


def test_web_shear_has_no_rolled_exception_and_counts_stiffeners() -> None:
    # h/tw = 68 > 2.24 sqrt(E/Fy) = 53.9: kv = 5.34 gives Cv1 = 1.10 sqrt(kv E/Fy) / 68.
    plain = shear_major(built_up_ishape(GIRDER), STEEL, "LRFD")
    cv1 = 1.10 * math.sqrt(5.34 * 29000 / 50) / 68
    assert plain.nominal == pytest.approx(0.6 * 50 * 36 * 0.5 * cv1)
    assert plain.available == pytest.approx(0.9 * plain.nominal)
    # Stiffeners at a = h: kv = 10, 1.10 sqrt(kv E/Fy) = 83.8 >= 68, so Cv1 = 1.
    stiffened = shear_major(
        built_up_ishape(GIRDER.model_copy(update={"stiffener_spacing": 34.0})), STEEL, "LRFD"
    )
    assert stiffened.nominal == pytest.approx(0.6 * 50 * 36 * 0.5)
    assert "kv = 10" in stiffened.equation
    # A stocky web: a rolled shape would take phi = 1.0; a built-up one keeps 0.9.
    stocky = built_up_ishape(GIRDER.model_copy(update={"tw": 1.0}))
    assert shear_major(stocky, STEEL, "LRFD").available == pytest.approx(0.9 * 0.6 * 50 * 36 * 1.0)


def test_a_slender_web_plate_girder_uses_f5() -> None:
    # h/tw = 46 / 0.3125 = 147 > 5.70 sqrt(E/Fy) = 137.
    girder = built_up_ishape(BuiltUpShape(name="PG2", d=48.0, bf=16.0, tf=1.0, tw=0.3125))
    assert slenderness(girder, STEEL).web_class == "slender"
    strength = flexure_major(girder, STEEL, "LRFD", unbraced=10.0)
    assert strength.equation.startswith("F5")


def test_the_analysis_section_is_oriented_like_a_rolled_one() -> None:
    props = built_up_ishape(GIRDER)
    two_d = analysis_section(
        GIRDER, section_id=5, elastic_modulus=29000.0, shear_modulus=11200.0, ndm=2
    )
    three_d = analysis_section(
        GIRDER, section_id=5, elastic_modulus=29000.0, shear_modulus=11200.0, ndm=3
    )
    assert (two_d.name, two_d.Iz, two_d.A) == (
        "PG1",
        pytest.approx(props.Ix),
        pytest.approx(props.A),
    )
    assert three_d.Iy == pytest.approx(props.Ix)
    assert three_d.Iz == pytest.approx(props.Iy)


def test_built_up_shapes_save_only_when_defined(tmp_path: Path) -> None:
    project = Project()
    project.design = DesignSettings()
    path = save_project(project, tmp_path / "plain.osmodel")
    assert "built_up" not in json.loads(path.read_text(encoding="utf-8"))["design"]
    project.design = DesignSettings(built_up=[GIRDER])
    path = save_project(project, tmp_path / "girder.osmodel")
    saved = json.loads(path.read_text(encoding="utf-8"))["design"]["built_up"]
    assert saved == [
        {"name": "PG1", "d": 36.0, "bf": 12.0, "tf": 1.0, "tw": 0.5, "stiffener_spacing": None}
    ]
    assert load_project(path).design.built_up_by_name()["PG1"] == GIRDER
