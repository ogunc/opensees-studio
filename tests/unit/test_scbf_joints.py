"""AISC 341-22 F2.6b: SCBF beam-to-column connection moment demand."""

from __future__ import annotations

import pytest

from opensees_studio.core.design.scbf_joints import scbf_beam_column_moment


def test_the_required_moment_is_the_lesser_of_beam_and_columns() -> None:
    moment = scbf_beam_column_moment(
        ry=1.1,
        beam_fy=50.0,
        beam_z=50.0,
        columns=[(50.0, 100.0)],
    )
    assert moment.beam_moment == pytest.approx(1.1 * 1.1 * 50.0 * 50.0)
    assert moment.column_moment == pytest.approx(1.1 * 1.1 * 50.0 * 100.0)
    assert moment.required == pytest.approx(moment.beam_moment)
    assert [step.label for step in moment.steps] == [
        "Beam expected moment",
        "Column expected moment",
        "Required moment",
    ]


def test_the_column_branch_sums_every_column() -> None:
    moment = scbf_beam_column_moment(
        ry=1.1,
        beam_fy=50.0,
        beam_z=200.0,
        columns=[(50.0, 60.0), (50.0, 40.0)],
    )
    assert moment.column_moment == pytest.approx(1.1 * 1.1 * 50.0 * 100.0)
    assert moment.required == pytest.approx(moment.column_moment)
    assert moment.required < moment.beam_moment


def test_asd_divides_both_branches_by_alpha_s() -> None:
    lrfd = scbf_beam_column_moment(ry=1.1, beam_fy=50.0, beam_z=50.0, columns=[(50.0, 100.0)])
    asd = scbf_beam_column_moment(
        ry=1.1,
        beam_fy=50.0,
        beam_z=50.0,
        columns=[(50.0, 100.0)],
        method="ASD",
    )
    assert asd.beam_moment == pytest.approx(lrfd.beam_moment / 1.5)
    assert asd.column_moment == pytest.approx(lrfd.column_moment / 1.5)
    assert asd.required == pytest.approx(lrfd.required / 1.5)


def test_the_inputs_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        scbf_beam_column_moment(ry=1.1, beam_fy=0.0, beam_z=50.0, columns=[(50.0, 100.0)])
    with pytest.raises(ValueError, match="positive"):
        scbf_beam_column_moment(ry=1.1, beam_fy=50.0, beam_z=50.0, columns=[(0.0, 100.0)])
    with pytest.raises(ValueError, match="positive"):
        scbf_beam_column_moment(ry=1.1, beam_fy=50.0, beam_z=50.0, columns=[])


def test_column_splice_demand_follows_f2_6d() -> None:
    from opensees_studio.core.design.scbf_joints import column_splice_demand

    splice = column_splice_demand(
        top_fy=50.0,
        top_z=100.0,
        bottom_fy=50.0,
        bottom_z=80.0,
        clear_height=144.0,
    )
    assert splice.moment == pytest.approx(0.5 * 50.0 * 80.0)
    assert splice.shear == pytest.approx((50.0 * 100.0 + 50.0 * 80.0) / 144.0)
    assert [step.label for step in splice.steps] == [
        "Top plastic moment",
        "Bottom plastic moment",
        "Required moment",
        "Required shear",
    ]

    asd = column_splice_demand(
        top_fy=50.0,
        top_z=100.0,
        bottom_fy=50.0,
        bottom_z=80.0,
        clear_height=144.0,
        method="ASD",
    )
    assert asd.moment == pytest.approx(splice.moment / 1.5)
    assert asd.shear == pytest.approx(splice.shear / 1.5)


def test_column_splice_inputs_must_be_positive() -> None:
    from opensees_studio.core.design.scbf_joints import column_splice_demand

    with pytest.raises(ValueError, match="positive"):
        column_splice_demand(
            top_fy=50.0,
            top_z=100.0,
            bottom_fy=50.0,
            bottom_z=80.0,
            clear_height=0.0,
        )
