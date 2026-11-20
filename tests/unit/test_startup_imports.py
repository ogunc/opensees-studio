"""The command-line entry points never load the splash, Qt's GUI or VTK."""

from __future__ import annotations

import subprocess
import sys
import textwrap


def _modules_after(code: str) -> set[str]:
    script = textwrap.dedent(code) + "\nimport sys\nprint('\\n'.join(sys.modules))\n"
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=120
    ).stdout
    return set(out.split())


def test_the_analysis_and_batch_cli_never_load_the_splash() -> None:
    for flag in ("CLI_FLAG", "BATCH_FLAG"):
        loaded = _modules_after(
            f"""
            import sys
            import opensees_studio.run, opensees_studio.batch
            from opensees_studio import child_cli
            opensees_studio.run.main = lambda argv=None: 0
            opensees_studio.batch.main = lambda argv=None: 0
            sys.argv = ["OpenSeesStudio", child_cli.{flag}]
            from opensees_studio.__main__ import main
            assert main() == 0
            """
        )
        assert "opensees_studio.views.splash" not in loaded, flag
        assert "opensees_studio.app" not in loaded, flag
        assert "PySide6.QtWidgets" not in loaded, flag


def test_the_dxf_readers_load_ezdxf_only_when_they_read() -> None:
    loaded = _modules_after(
        "import opensees_studio.services.dxf_import, opensees_studio.services.section_dxf"
    )
    assert "ezdxf" not in loaded
