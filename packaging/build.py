"""Build the end-user desktop bundle and prove it can run an analysis.

Usage (from anywhere; paths are resolved from this file)::

    python packaging/build.py              # build + smoke test
    python packaging/build.py --no-smoke   # build only, quicker
    python packaging/build.py --zip        # also write dist/OpenSeesStudio-<os>.zip

The smoke test is the part that matters. A frozen bundle can start and still
fail at the one thing a structural engineer needs it for: solving. The GUI
runs every analysis by re-running the bundle as the analysis CLI
(``opensees_studio.child_cli``), and a mistake there — a missing OpenSees
shared library, a module that only exists in the source tree — is invisible
until an actual run. So the smoke test drives that exact entry point on a
bundled example and requires a result file plus a manifest entry.
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


def smoke_test() -> None:
    """Solve a bundled example through the frozen CLI entry point."""
    exe = executable_path()
    if not exe.exists():
        raise SystemExit(f"[smoke] no executable at {exe}")
    if not SMOKE_PROJECT.exists():
        raise SystemExit(f"[smoke] missing example {SMOKE_PROJECT}")

    with tempfile.TemporaryDirectory(prefix="osstudio-smoke-") as tmp:
        out_dir = Path(tmp) / "out"
        cmd = [
            str(exe),
            CLI_FLAG,
            "--project",
            str(SMOKE_PROJECT),
            "--cases",
            str(SMOKE_CASE),
            "--out",
            str(out_dir),
        ]
        print(f"[smoke] {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        tail = "\n".join((proc.stdout or "").splitlines()[-4:])
        if proc.returncode != 0:
            raise SystemExit(
                f"[smoke] the frozen CLI exited with {proc.returncode}\n"
                f"--- stdout tail ---\n{tail}\n--- stderr tail ---\n"
                + "\n".join((proc.stderr or "").splitlines()[-20:])
            )

        manifest = out_dir / "manifest.json"
        if not manifest.is_file():
            raise SystemExit(f"[smoke] no manifest written to {out_dir}\n{tail}")
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
        smoke_test()
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
