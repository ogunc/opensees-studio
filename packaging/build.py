"""Build the end-user desktop bundle and prove it can run an analysis.

Usage (from anywhere; paths are resolved from this file)::

    python packaging/build.py              # build + smoke test
    python packaging/build.py --no-smoke   # build only, quicker
    python packaging/build.py --zip        # also write dist/OpenSeesStudio-<os>.zip

The smoke test is the part that matters. A frozen bundle can start and still
fail at the one thing a structural engineer needs it for: solving. The GUI
runs every analysis by re-running the bundle as the analysis CLI
(``opensees_studio.child_cli``), and a mistake there — a module that only
exists in the source tree, an engine folder the frozen interpreter cannot
load — is invisible until an actual run.

The bundle does not carry OpenSeesPy (ADR-0003), so the smoke test proves both
halves: the frozen CLI **without** a solver refuses with the message that sends
the user to Options > Solver, and the same CLI solves a bundled example once
OpenSeesPy is installed by the application's own installer
(``services.engine_install``, the code behind the in-app download) into a
temporary folder. ``--engine-dir`` reuses a folder already holding it, for a
build without network.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
ROOT = PACKAGING_DIR.parent
SPEC = PACKAGING_DIR / "opensees-studio.spec"
APP_NAME = "OpenSeesStudio"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

CLI_FLAG = "--run-analysis-cli"  # opensees_studio.child_cli.CLI_FLAG
SMOKE_PROJECT = ROOT / "examples" / "cantilever.osmodel"
SMOKE_CASE = 1  # Static, "Tip-Load"


def platform_suffix() -> str:
    """Which platform this build is for, as it appears in the archive name.

    From ``sys.platform``, not ``os.name``: ``os.name`` is ``"posix"`` on both
    Linux and macOS, so asking it produced a macOS bundle named
    ``OpenSeesStudio-linux.zip`` — which then overwrote the Linux archive on
    the release, because both jobs attach to the same one.
    """
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def executable_path() -> Path:
    """The bundle's executable on this platform."""
    name = f"{APP_NAME}.exe" if sys.platform.startswith("win") else APP_NAME
    return DIST / APP_NAME / name


def bundle_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / 1024 / 1024


def build(clean: bool) -> None:
    """Run PyInstaller with the spec."""
    if clean:
        for target in (BUILD, DIST / APP_NAME):
            shutil.rmtree(target, ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)]
    print(f"[build] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=ROOT, check=True)


def _run_cli(out_dir: Path, engine_dir: Path | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "OPENSEES_STUDIO_ENGINE_PATH"}
    if engine_dir is not None:
        env["OPENSEES_STUDIO_ENGINE_PATH"] = str(engine_dir)
    cmd = [
        str(executable_path()),
        CLI_FLAG,
        "--project",
        str(SMOKE_PROJECT),
        "--cases",
        str(SMOKE_CASE),
        "--out",
        str(out_dir),
    ]
    print(f"[smoke] {' '.join(cmd)}" + (f"  (engine: {engine_dir})" if engine_dir else ""))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    return (
        "--- stdout tail ---\n"
        + "\n".join((proc.stdout or "").splitlines()[-4:])
        + "\n--- stderr tail ---\n"
        + "\n".join((proc.stderr or "").splitlines()[-20:])
    )


def _engine_folder(tmp: Path, engine_dir: Path | None) -> Path:
    """OpenSeesPy installed the way the user installs it (or the folder given)."""
    if engine_dir is not None:
        return engine_dir
    from opensees_studio.services.engine_install import install_opensees

    print("[smoke] installing OpenSeesPy with the application's installer ...")
    settings = install_opensees(tmp / "engines")
    assert settings.package_dir is not None
    return Path(settings.package_dir)


def smoke_test(engine_dir: Path | None = None) -> None:
    """The frozen CLI refuses without a solver, and solves an example with one."""
    exe = executable_path()
    if not exe.exists():
        raise SystemExit(f"[smoke] no executable at {exe}")
    if not SMOKE_PROJECT.exists():
        raise SystemExit(f"[smoke] missing example {SMOKE_PROJECT}")

    with tempfile.TemporaryDirectory(prefix="osstudio-smoke-") as tmp_name:
        tmp = Path(tmp_name)

        refused = _run_cli(tmp / "no-solver", None)
        if refused.returncode != 2 or "Options" not in (refused.stdout or ""):
            raise SystemExit(
                "[smoke] without a solver the frozen CLI should exit 2 and point to "
                f"Options > Solver; it exited {refused.returncode}\n{_tail(refused)}"
            )
        print("[smoke] ok: without a solver the CLI refuses and points to Options > Solver")

        out_dir = tmp / "out"
        proc = _run_cli(out_dir, _engine_folder(tmp, engine_dir))
        if proc.returncode != 0:
            raise SystemExit(f"[smoke] the frozen CLI exited with {proc.returncode}\n{_tail(proc)}")
        manifest = out_dir / "manifest.json"
        if not manifest.is_file():
            raise SystemExit(f"[smoke] no manifest written to {out_dir}\n{_tail(proc)}")
        entry = json.loads(manifest.read_text(encoding="utf-8"))["cases"][0]
        results = list(out_dir.glob("*.h5"))
        if not results:
            raise SystemExit(f"[smoke] no result file in {out_dir}")
        print(
            f"[smoke] ok: case {entry['case_id']} ({entry['case_name']}) -> "
            f"{', '.join(f.name for f in results)}"
        )


def smoke_test_gui(timeout_s: int = 20) -> None:
    """Start the frozen GUI and require that it stays up.

    The CLI test above proves the solver works; this one catches a bundle
    that is missing a Qt plugin or a VTK library, where the window never
    appears and the process dies within a second. Needs a display (CI wraps
    it in ``xvfb-run`` on Linux); without one it is skipped.
    """
    if os.name != "nt" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("[smoke] no display available; skipping the GUI start test")
        return
    exe = executable_path()
    proc = subprocess.Popen([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print(f"[smoke] ok: the GUI stayed up for {timeout_s} s")
    else:
        stderr = (proc.stderr.read() or "").splitlines()[-15:]
        raise SystemExit(
            f"[smoke] the GUI exited on its own with {proc.returncode}\n" + "\n".join(stderr)
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
            proc.kill()
            proc.wait(timeout=10)


def make_zip() -> Path:
    """Zip the bundle for handing to a user."""
    target = DIST / f"{APP_NAME}-{platform_suffix()}.zip"
    folder = DIST / APP_NAME
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DIST))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-smoke", action="store_true", help="skip the analysis smoke test")
    parser.add_argument(
        "--gui-smoke",
        action="store_true",
        help="also start the GUI and check that it stays up (needs a display)",
    )
    parser.add_argument("--no-clean", action="store_true", help="reuse the PyInstaller cache")
    parser.add_argument(
        "--engine-dir",
        type=Path,
        help="folder already holding OpenSeesPy for the smoke test (default: download it)",
    )
    parser.add_argument("--zip", action="store_true", help="also write dist/<name>-<os>.zip")
    parser.add_argument(
        "--zip-only",
        action="store_true",
        help="pack the existing bundle and stop: signing has to happen before zipping",
    )
    args = parser.parse_args(argv)

    if args.zip_only:
        archive = make_zip()
        print(f"[build] archive: {archive} ({archive.stat().st_size / 1024 / 1024:.0f} MB)")
        return 0

    build(clean=not args.no_clean)
    if not args.no_smoke:
        smoke_test(args.engine_dir)
    if args.gui_smoke:
        smoke_test_gui()

    bundle = DIST / APP_NAME
    print(f"[build] bundle: {bundle} ({bundle_size_mb(bundle):.0f} MB)")
    print(f"[build] run it with: {executable_path()}")
    if args.zip:
        archive = make_zip()
        print(f"[build] archive: {archive} ({archive.stat().st_size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
