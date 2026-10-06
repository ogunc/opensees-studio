"""Official example 07. W-shape editor templates replace WFSection2d.

Source node tags map to consecutive GUI tags in NODE_TAG_MAP. Element tags
map to consecutive GUI tags in ELEMENT_TAG_MAP. Section/material tags agree.
"""

from examples.official._common import Builder, c, save_built

NODE_TAG_MAP = {
    source: target
    for target, source in enumerate(
        [
            1,
            2,
            3,
            11,
            12,
            13,
            21,
            22,
            23,
            31,
            32,
            33,
            1101,
            1201,
            1202,
            1301,
            2101,
            2201,
            2202,
            2301,
            3101,
            3201,
            3202,
            3301,
        ],
        1,
    )
}
ELEMENT_TAG_MAP = {
    source: target
    for target, source in enumerate(
        [1, 2, 3, 11, 12, 13, 21, 22, 23, 101, 102, 201, 202, 301, 302], 1
    )
}


def build_three_story_steel(replay=None, vm=None):
    b = Builder("Official 07: Three-storey steel", replay=replay, vm=vm)
    for floor in range(4):
        for x in (0, 192, 384):
            b.node(x, floor * 120)
    for floor in range(1, 4):
        for x in (0, 192, 192, 384):
            b.node(x, floor * 120)
    b.support([1, 2, 3])
    b.material(
        c.Steel02(
            id=1,
            name="Steel with isotropic hardening",
            Fy=60,
            E0=29000,
            b=0.1,
            R0=18,
            cR1=0.925,
            cR2=0.15,
            a1=0.05,
            a2=1,
            a3=0.05,
            a4=1,
        )
    )
    shapes = [
        (10.5, 0.26, 5.77, 0.44, 15, 16),
        (10.5, 0.26, 5.77, 0.44, 15, 16),
        (8.3, 0.44, 8.11, 0.685, 15, 15),
        (8.2, 0.40, 8.01, 0.650, 15, 15),
        (8.0, 0.40, 7.89, 0.600, 15, 15),
    ]
    for sid, (d, tw, bf, tf, nw, nf) in enumerate(shapes, 1):
        template = dict(d=d, tw=tw, bf=bf, tf=tf, n_web=nw, n_flange=nf)
        b.section(
            c.FiberSection(id=sid, name=f"W-shape {sid}", patches=c.w_shape_patches(1, **template)),
            template,
        )
    eid = 1
    for floor in range(3):
        for column in range(3):
            ni = floor * 3 + column + 1
            b.element(
                c.ForceBeamColumn(
                    id=eid,
                    nodes=(ni, ni + 3),
                    section_id=2 if column == 1 else 1,
                    geom_transf="PDelta",
                    integration_points=4,
                )
            )
            eid += 1
    for floor in range(3):
        for bay in range(2):
            ni = 13 + floor * 4 + bay * 2
            b.element(
                c.ForceBeamColumn(
                    id=eid, nodes=(ni, ni + 1), section_id=floor + 3, integration_points=4
                )
            )
            eid += 1
    for floor in range(3):
        for offset, retained in enumerate([4, 5, 5, 6]):
            b.equal(retained + floor * 3, 13 + floor * 4 + offset, [1, 2, 3])
    b.pattern(1, "Gravity")
    b.load(1, [4, 6, 7, 9, 10, 12], fy=-5)
    b.load(1, [5, 8, 11], fy=-6)
    b.case(
        c.StaticCase(
            id=1,
            name="Gravity",
            pattern_ids=[1],
            n_steps=10,
            load_factor_increment=0.1,
            system="BandGeneral",
            numberer="Plain",
            algorithm="Newton",
            test="NormUnbalance",
            tolerance=1e-8,
            max_iter=10,
        )
    )
    b.pattern(2, "Lateral loads", series_id=1)
    for nid, force in [(4, 1.61), (7, 3.22), (10, 4.83)]:
        b.load(2, [nid], fx=force)
    b.case(
        c.PushoverCase(
            id=2,
            name="Pushover",
            pattern_ids=[2],
            preload_case_ids=[1],
            control_node=10,
            control_dof=1,
            target_disp=18,
            step_size=0.1,
            base_nodes=[1, 2, 3],
            system="ProfileSPD",
            numberer="Plain",
            algorithm="Newton",
            test="NormUnbalance",
            tolerance=1e-8,
            max_iter=10,
        )
    )
    return b.finish()


def main():
    save_built(build_three_story_steel(), __file__)


if __name__ == "__main__":
    main()
