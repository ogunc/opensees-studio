"""Tests for the optional, cosmetic section-shape hint on ``ElasticSection``.

The shape (pipe/angle/rect) is a *drawing hint* only — it records the true
cross-section geometry so a viewer can extrude a tube as a tube and an angle as
an L, instead of back-solving an equivalent box from A/Iz. It is never emitted to
OpenSees and never read by the runner, so attaching one must never perturb the
stiffness fields the analysis actually uses.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    AngleShape,
    ElasticSection,
    PipeShape,
    RectShape,
)


def _elastic(**over: object) -> ElasticSection:
    base: dict[str, object] = dict(
        id=1, name="S", E=210e6, A=0.017279, Iz=1.642e-4, Iy=1.642e-4, G=27.7e6, J=3.284e-4
    )
    base.update(over)
    return ElasticSection(**base)  # type: ignore[arg-type]


# ── default + back-compat ─────────────────────────────────────────
def test_shape_defaults_to_none() -> None:
    """An ElasticSection built without a shape has none — older models load fine."""
    assert _elastic().shape is None


def test_legacy_json_without_shape_still_validates() -> None:
    """A serialised section that predates the field (no ``shape`` key) round-trips."""
    sec = ElasticSection.model_validate(
        {"id": 1, "name": "S", "type": "ElasticSection", "E": 1.0, "A": 1.0, "Iz": 1.0}
    )
    assert sec.shape is None


# ── the three shape kinds ─────────────────────────────────────────
def test_pipe_shape_roundtrips() -> None:
    sec = _elastic(shape=PipeShape(od=0.295, t=0.020))
    restored = ElasticSection.model_validate(sec.model_dump(mode="json"))
    assert isinstance(restored.shape, PipeShape)
    assert restored.shape.od == pytest.approx(0.295)
    assert restored.shape.t == pytest.approx(0.020)


def test_angle_shape_roundtrips() -> None:
    sec = _elastic(shape=AngleShape(d=0.08, b=0.08, t=0.008))
    restored = ElasticSection.model_validate(sec.model_dump(mode="json"))
    assert isinstance(restored.shape, AngleShape)
    assert restored.shape.d == pytest.approx(0.08)
    assert restored.shape.b == pytest.approx(0.08)
    assert restored.shape.t == pytest.approx(0.008)


def test_rect_shape_roundtrips() -> None:
    sec = _elastic(shape=RectShape(d=0.13, b=0.016))
    restored = ElasticSection.model_validate(sec.model_dump(mode="json"))
    assert isinstance(restored.shape, RectShape)
    assert (restored.shape.d, restored.shape.b) == pytest.approx((0.13, 0.016))


def test_shape_accepts_a_plain_dict_via_the_kind_discriminator() -> None:
    """A builder may pass a dict; the discriminated union selects the right class."""
    sec = _elastic(shape={"kind": "pipe", "od": 0.37, "t": 0.03})
    assert isinstance(sec.shape, PipeShape)


# ── the hint never touches the analysis fields ────────────────────
def test_shape_does_not_change_the_stiffness_fields() -> None:
    """Attaching a shape leaves A/Iz/Iy/J byte-identical — same emission to OpenSees."""
    plain = _elastic()
    shaped = _elastic(shape=PipeShape(od=0.295, t=0.020))
    for f in ("E", "A", "Iz", "Iy", "G", "J"):
        assert getattr(plain, f) == getattr(shaped, f)
    # The only difference in the serialised form is the added shape key.
    pj, sj = plain.model_dump(mode="json"), shaped.model_dump(mode="json")
    assert sj.pop("shape") == {"kind": "pipe", "od": 0.295, "t": 0.020}
    assert pj.pop("shape") is None
    assert pj == sj


# ── validation guards ─────────────────────────────────────────────
def test_unknown_shape_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _elastic(shape={"kind": "ibeam", "d": 0.1, "b": 0.1})


def test_shape_dims_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _elastic(shape={"kind": "pipe", "od": 0.0, "t": 0.01})
