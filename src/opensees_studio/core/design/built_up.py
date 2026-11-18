"""Section properties of a welded doubly symmetric I-shape, from its plates.

For flanges ``bf x tf`` and a web ``tw`` over the clear height
``h = d - 2 tf`` (welds neglected):

    A  = 2 bf tf + h tw
    Ix = (bf d^3 - (bf - tw) h^3) / 12
    Iy = (2 tf bf^3 + h tw^3) / 12
    Zx = bf tf (d - tf) + tw h^2 / 4
    Zy = tf bf^2 / 2 + h tw^2 / 4
    J  = (2 bf tf^3 + (d - tf) tw^3) / 3       (thin-walled open section)
    Cw = Iy ho^2 / 4,  ho = d - tf

The result is a :class:`~core.design.aisc360.BuiltUpIShape`, checked by the
AISC 360 member check with the built-up rules (``kc`` flange limits, web shear
with stiffeners). :func:`analysis_section` gives the matching elastic section,
oriented as ``core.aisc.shape_to_elastic_section`` orients a rolled one.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math

from opensees_studio.core.design.aisc360 import BuiltUpIShape
from opensees_studio.core.design.built_up_model import BuiltUpShape
from opensees_studio.core.sections import ElasticSection


def built_up_ishape(shape: BuiltUpShape) -> BuiltUpIShape:
    """The member check's view of ``shape``: every property from the plates."""
    d, bf, tf, tw = shape.d, shape.bf, shape.tf, shape.tw
    h = d - 2.0 * tf
    area = 2.0 * bf * tf + h * tw
    ix = (bf * d**3 - (bf - tw) * h**3) / 12.0
    iy = (2.0 * tf * bf**3 + h * tw**3) / 12.0
    ho = d - tf
    return BuiltUpIShape(
        name=shape.name,
        A=area,
        d=d,
        bf=bf,
        tw=tw,
        tf=tf,
        Ix=ix,
        Iy=iy,
        Zx=bf * tf * ho + tw * h**2 / 4.0,
        Zy=tf * bf**2 / 2.0 + h * tw**2 / 4.0,
        Sx=ix / (d / 2.0),
        Sy=iy / (bf / 2.0),
        rx=math.sqrt(ix / area),
        ry=math.sqrt(iy / area),
        J=(2.0 * bf * tf**3 + ho * tw**3) / 3.0,
        Cw=iy * ho**2 / 4.0,
        stiffener_spacing=shape.stiffener_spacing,
    )


def analysis_section(
    shape: BuiltUpShape,
    *,
    section_id: int,
    elastic_modulus: float,
    shear_modulus: float,
    ndm: int,
) -> ElasticSection:
    """An elastic section with ``shape``'s properties, named after it.

    In 2D the frame bends about local z, so ``Iz = Ix``; in 3D a beam carries its
    depth along local z, so ``Iy = Ix`` and ``Iz`` is the weak-axis inertia — the
    orientation of :func:`core.aisc.shape_to_elastic_section`.
    """
    props = built_up_ishape(shape)
    iz, iy = props.Ix, props.Iy
    if ndm == 3:
        iz, iy = iy, iz
    return ElasticSection(
        id=section_id,
        name=shape.name,
        E=elastic_modulus,
        G=shear_modulus,
        A=props.A,
        Iz=iz,
        Iy=iy,
        J=props.J,
    )
