"""Official example 06. Preserve the published loop's 151 increments to 15.1."""

from examples.official._common import Builder, c, rc_frame, save_built


def build_rc_frame_pushover(replay=None, vm=None):
    b = Builder("Official 06: RC frame pushover", replay=replay, vm=vm)
    rc_frame(b)
    b.pattern(2, "Lateral loads", series_id=1)
    b.load(2, [3, 4], fx=10)
    b.case(
        c.PushoverCase(
            id=2,
            name="ModifiedNewton initial",
            pattern_ids=[2],
            preload_case_ids=[1],
            control_node=3,
            control_dof=1,
            target_disp=151 * 0.1,
            step_size=0.1,
            base_nodes=[1, 2],
            system="BandGeneral",
            constraints="Transformation",
            algorithm="ModifiedNewton",
            algorithm_args=("-initial",),
            tolerance=1e-12,
            max_iter=1000,
        )
    )
    return b.finish()


def main():
    save_built(build_rc_frame_pushover(), __file__)


if __name__ == "__main__":
    main()
