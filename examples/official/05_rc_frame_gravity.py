"""Official example 05. Five-point Lobatto integration and PDelta columns."""

from examples.official._common import Builder, rc_frame, save_built


def build_rc_frame_gravity(replay=None, vm=None):
    b = Builder("Official 05: RC frame gravity", replay=replay, vm=vm)
    rc_frame(b)
    return b.finish()


def main():
    save_built(build_rc_frame_gravity(), __file__)


if __name__ == "__main__":
    main()
