"""Solver engines: which program solves the model, and where it is installed.

The application does not ship a solver of its own. It models, and an *engine*
solves: today the only one is **OpenSeesPy**, a separate program with its own
license, which may or may not be installed next to the application. Without an
engine the application still models, exports and reports; only running an
analysis (and the two tools that call OpenSees directly, the stability check
and the Material Tester) needs one.

Where OpenSeesPy comes from is a user setting (:class:`SolverSettings`, kept in
``solver.json`` in the application data directory):

* the application's own Python environment (``pip install
  opensees-studio[opensees]``, or a bundle that includes it);
* another Python installation of the same minor version, whose ``openseespy``
  the user points at (:func:`inspect_python` asks that interpreter where it is);
* a folder that holds the ``openseespy`` package (what an in-app download will
  unpack into).

The folder of the last two is **appended** to ``sys.path`` of the process that
needs OpenSees (:func:`activate`) — the analysis child receives it in
:data:`ENGINE_PATH_ENV` — so the application's own libraries keep precedence and
only what it lacks is found there.

Engines beyond the built-in one register as ``opensees_studio.engines`` entry
points: an object with the :class:`SolverEngine` members. See
``docs/adr/ADR-0003-solver-engines.md`` for the contract.

Nothing here imports OpenSeesPy: detection uses ``importlib`` specs and package
metadata, so checking for a solver never loads its native library.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from opensees_studio.services.persistence import app_data_dir

#: Environment variable that hands the engine's package folder to the analysis child.
ENGINE_PATH_ENV = "OPENSEES_STUDIO_ENGINE_PATH"

#: Environment variable that tells the analysis child which engine solves.
ENGINE_KEY_ENV = "OPENSEES_STUDIO_ENGINE"

#: File in the application data directory that holds :class:`SolverSettings`.
SETTINGS_FILE = "solver.json"

#: Key of the built-in engine.
OPENSEES_PY = "openseespy"

#: Case types the OpenSeesPy engine runs (``AnalysisCase.type``).
OPENSEES_CASE_TYPES = frozenset(
    {"Static", "Modal", "Transient", "Pushover", "ResponseSpectrum", "InfluenceLine"}
)

#: How long :func:`inspect_python` waits for another interpreter to answer.
INSPECT_TIMEOUT_S = 30.0

ENTRY_POINT_GROUP = "opensees_studio.engines"


class EngineError(RuntimeError):
    """An engine location that cannot be used, with the reason for the user."""


@dataclass(frozen=True)
class SolverSettings:
    """Which engine solves, and where its package is when it is not in this environment."""

    engine: str = OPENSEES_PY
    package_dir: str | None = None  # a folder appended to sys.path, None = this environment
    python: str | None = None  # the interpreter package_dir came from (shown to the user)


@dataclass(frozen=True)
class EngineStatus:
    """What the user sees about the engine: is it there, which version, from where."""

    engine: str
    name: str
    available: bool
    version: str | None = None
    location: str | None = None
    message: str = ""
    case_types: frozenset[str] = field(default_factory=frozenset)

    def summary(self) -> str:
        if not self.available:
            return f"{self.name}: not available. {self.message}".strip()
        where = f" from {self.location}" if self.location else ""
        version = f" {self.version}" if self.version else ""
        return f"{self.name}{version}{where}"


class SolverEngine(Protocol):
    """What an engine provides to the application."""

    key: str
    name: str
    case_types: frozenset[str]

    def status(self, settings: SolverSettings) -> EngineStatus:
        """Whether the engine can run here, without loading it."""

    def child_environment(self, settings: SolverSettings) -> dict[str, str]:
        """Variables the analysis child needs to find the engine."""

    def create_runner(self, project: Any, on_progress: Any = None) -> Any:
        """In the analysis child: an object whose ``run(case, results_dir=...)``
        returns the same results classes ``OpenSeesRunner`` does."""


# ──────────────────────────── settings ────────────────────────────
def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILE


def load_settings() -> SolverSettings:
    """The saved settings, or the defaults when there are none (or they are unreadable)."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return SolverSettings(
            engine=str(data.get("engine") or OPENSEES_PY),
            package_dir=data.get("package_dir") or None,
            python=data.get("python") or None,
        )
    except (OSError, ValueError, AttributeError):
        return SolverSettings()


def save_settings(settings: SolverSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")


# ──────────────────────────── OpenSeesPy ────────────────────────────
def _version_in(folder: Path | None) -> str | None:
    """Installed ``openseespy`` version, read from its metadata (in ``folder`` if given)."""
    try:
        if folder is None:
            return importlib.metadata.version("openseespy")
        for dist in importlib.metadata.distributions(path=[str(folder)]):
            if (dist.metadata["Name"] or "").lower() == "openseespy":
                return str(dist.version)
    except importlib.metadata.PackageNotFoundError:
        return None
    return None


class OpenSeesPyEngine:
    """The built-in engine: OpenSeesPy, run through ``opensees_studio.run``."""

    key = OPENSEES_PY
    name = "OpenSeesPy"
    case_types = OPENSEES_CASE_TYPES

    def status(self, settings: SolverSettings) -> EngineStatus:
        def report(
            available: bool,
            version: str | None = None,
            location: str | None = None,
            message: str = "",
        ) -> EngineStatus:
            return EngineStatus(
                engine=self.key,
                name=self.name,
                available=available,
                version=version,
                location=location,
                message=message,
                case_types=self.case_types,
            )

        own = importlib.util.find_spec("openseespy")
        if settings.package_dir:
            folder = Path(settings.package_dir)
            if own is not None and own.origin and not Path(own.origin).is_relative_to(folder):
                # The folder is appended to sys.path: this environment's copy wins.
                return report(
                    available=True,
                    version=_version_in(None),
                    message=(
                        f"OpenSees Studio's own environment has OpenSeesPy, so {folder} "
                        "is not used."
                    ),
                )
            if not (folder / "openseespy" / "__init__.py").is_file():
                return report(
                    available=False,
                    location=str(folder),
                    message=f"No openseespy package in {folder}. Choose another in Options → Solver.",
                )
            return report(available=True, version=_version_in(folder), location=str(folder))
        if own is None:
            return report(
                available=False,
                message=(
                    "OpenSeesPy is not installed. Point to an installation in "
                    "Options → Solver, or install it with: pip install openseespy==3.8.0.0"
                ),
            )
        return report(available=True, version=_version_in(None))

    def child_environment(self, settings: SolverSettings) -> dict[str, str]:
        return {ENGINE_PATH_ENV: settings.package_dir} if settings.package_dir else {}

    def create_runner(self, project: Any, on_progress: Any = None) -> Any:
        from opensees_studio.services.opensees_runner import OpenSeesRunner

        return OpenSeesRunner(project, on_progress=on_progress)


#: Key of the bundled PyNite engine.
PYNITE = "pynite"


class PyNiteEngine:
    """PyNite (MIT): linear static and P-Delta analysis of elastic frames.

    Shipped with the application (the ``gui`` extra), so it needs no download.
    What it models and what it refuses is in ``services.pynite_runner``.
    """

    key = PYNITE
    name = "PyNite"
    case_types = frozenset({"Static"})

    def status(self, settings: SolverSettings) -> EngineStatus:
        if importlib.util.find_spec("Pynite") is None:
            return EngineStatus(
                engine=self.key,
                name=self.name,
                available=False,
                message="PyNite is not installed: pip install PyNiteFEA==3.2.0",
                case_types=self.case_types,
            )
        try:
            version = importlib.metadata.version("PyNiteFEA")
        except importlib.metadata.PackageNotFoundError:
            version = None
        return EngineStatus(
            engine=self.key,
            name=self.name,
            available=True,
            version=version,
            case_types=self.case_types,
        )

    def child_environment(self, settings: SolverSettings) -> dict[str, str]:
        return {}

    def create_runner(self, project: Any, on_progress: Any = None) -> Any:
        from opensees_studio.services.pynite_runner import PyNiteRunner

        return PyNiteRunner(project, on_progress=on_progress)


# ──────────────────────────── registry ────────────────────────────
def engines() -> dict[str, SolverEngine]:
    """The built-in engines plus every one registered under :data:`ENTRY_POINT_GROUP`.

    A plug-in that fails to load is skipped: a broken third-party engine must
    not stop the application from starting.
    """
    found: dict[str, SolverEngine] = {OPENSEES_PY: OpenSeesPyEngine(), PYNITE: PyNiteEngine()}
    for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            engine = entry.load()
            engine = engine() if isinstance(engine, type) else engine
        except Exception:
            continue
        found.setdefault(engine.key, engine)
    return found


def engine_for(settings: SolverSettings) -> SolverEngine:
    """The engine ``settings`` names, the built-in one if that is not installed."""
    available = engines()
    return available.get(settings.engine, available[OPENSEES_PY])


def current_status(settings: SolverSettings | None = None) -> EngineStatus:
    """Status of the configured engine (the saved settings when none are given)."""
    settings = load_settings() if settings is None else settings
    return engine_for(settings).status(settings)


def child_environment(settings: SolverSettings | None = None) -> dict[str, str]:
    """What the analysis child needs: the chosen engine, and where OpenSeesPy is.

    The OpenSeesPy folder goes along whatever engine solves: the stability
    check and the Material Tester always run on OpenSees.
    """
    settings = load_settings() if settings is None else settings
    engine = engine_for(settings)
    env = {ENGINE_KEY_ENV: engine.key, **OpenSeesPyEngine().child_environment(settings)}
    env.update(engine.child_environment(settings))
    return env


def opensees_status(settings: SolverSettings | None = None) -> EngineStatus:
    """Whether OpenSeesPy itself is usable (the stability check and the Material Tester)."""
    settings = load_settings() if settings is None else settings
    return OpenSeesPyEngine().status(settings)


def engine_in_child() -> SolverEngine | None:
    """In the analysis child: the engine the parent chose, None when it is not installed here."""
    import os

    key = os.environ.get(ENGINE_KEY_ENV) or OPENSEES_PY
    return engines().get(key)


def unsupported_cases(engine: SolverEngine, cases: list[Any]) -> list[Any]:
    """The cases ``engine`` cannot run (by ``case.type``)."""
    return [case for case in cases if getattr(case, "type", None) not in engine.case_types]


def activate(package_dir: str | None) -> None:
    """Make ``package_dir`` importable in this process (appended, never in front)."""
    if package_dir and package_dir not in sys.path:
        sys.path.append(package_dir)


def activate_from_environment() -> None:
    """In the analysis child: pick up the folder the parent passed in :data:`ENGINE_PATH_ENV`."""
    import os

    activate(os.environ.get(ENGINE_PATH_ENV))


# ──────────────────────────── another Python ────────────────────────────
_PROBE = """\
import importlib.metadata, importlib.util, json, os, sys
spec = importlib.util.find_spec("openseespy")
out = {"python": list(sys.version_info[:2])}
if spec is not None and spec.submodule_search_locations:
    out["package_dir"] = os.path.dirname(list(spec.submodule_search_locations)[0])
    try:
        out["version"] = importlib.metadata.version("openseespy")
    except importlib.metadata.PackageNotFoundError:
        pass
print(json.dumps(out))
"""


def inspect_python(executable: str) -> SolverSettings:
    """Settings that use the ``openseespy`` installed for ``executable``.

    The interpreter is asked, without importing OpenSees, where its
    ``openseespy`` lives. It must be the same minor version as this one: the
    native library inside OpenSeesPy is built for one Python.

    Raises:
        EngineError: when the interpreter does not run, is another Python
            version, or has no ``openseespy``.
    """
    try:
        done = subprocess.run(
            [executable, "-I", "-c", _PROBE],
            capture_output=True,
            text=True,
            timeout=INSPECT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EngineError(f"Could not run {executable}: {exc}") from exc
    try:
        answer = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise EngineError(f"{executable} is not a Python interpreter that answered.") from exc
    wanted = list(sys.version_info[:2])
    if answer.get("python") != wanted:
        got = ".".join(str(v) for v in answer.get("python", []))
        raise EngineError(
            f"{executable} is Python {got}; OpenSeesPy has to run on Python "
            f"{wanted[0]}.{wanted[1]}, the version of this application."
        )
    if not answer.get("package_dir"):
        raise EngineError(
            f"{executable} has no openseespy. Install it there with: "
            f"{executable} -m pip install openseespy==3.8.0.0"
        )
    return SolverSettings(engine=OPENSEES_PY, package_dir=answer["package_dir"], python=executable)
