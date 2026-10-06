"""Official example 04. SparseGeneral always pivots in OpenSeesPy 3.8.0."""

from examples.official._common import Builder, c, rc_section, save_built


def build_moment_curvature(replay=None, vm=None):
    b = Builder("Official 04: Moment curvature", replay=replay, vm=vm)
    b.node(0, 0)
    b.node(0, 0)
    b.support([1])
    b.support([2], ux=False, uy=True, rz=False)
    rc_section(b)
    b.element(c.ZeroLengthSectionElement(id=1, nodes=(1, 2), section_id=1))
    b.pattern(1, "Axial preload", constant=True)
    b.load(1, [2], fx=-180)
    b.pattern(2, "Reference moment")
    b.load(2, [2], mz=1)
    opts = dict(
        system="SparseGeneral",
        numberer="Plain",
        algorithm="Newton",
        test="NormUnbalance",
        tolerance=1e-9,
        max_iter=10,
    )
    b.case(
        c.StaticCase(id=1, name="Axial preload", pattern_ids=[1], load_factor_increment=0, **opts)
    )
    target = (60 / 30000) / (0.7 * 22.5) * 15
    b.case(
        c.PushoverCase(
            id=2,
            name="Moment curvature",
            pattern_ids=[2],
            preload_case_ids=[1],
            control_node=2,
            control_dof=3,
            target_disp=target,
            step_size=target / 100,
            base_nodes=[1],
            **opts,
        )
    )
    return b.finish()


def main():
    save_built(build_moment_curvature(), __file__)


if __name__ == "__main__":
    main()
