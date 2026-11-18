# ADR-0003: The solver is an optional engine

- Status: accepted
- Date: 2026-10-21

## 1. Context

OpenSees Studio has always shipped OpenSeesPy as a base dependency and inside
its frozen bundle. Two reasons to stop:

- **License.** OpenSeesPy's own license: free for research, education and
  internal use; *commercial redistribution* of an application that uses
  `import openseespy` needs a license from its authors. OpenSees Studio is free
  software whose users may design structures commercially. Not redistributing
  OpenSeesPy keeps the project out of that question and leaves each user to
  install it under its authors' terms.
- **More than one solver.** Other engines are planned. A model should not be
  tied to the program that solves it.

Most of the application never needed OpenSees: modelling, the OpenSeesPy script
export, IFC, the report and reading stored results are pure Python. Only three
`services` modules import it (`opensees_runner`, `stability`, `material_tester`),
already lazily, and every analysis runs in a child process.

## 2. Decision

1. `openseespy` leaves the base dependencies for an `opensees` extra
   (`pip install opensees-studio[opensees]`); `dev` includes it, so the test
   suites still solve.
2. `services/engines.py` (no Qt) owns the choice of engine:
   - `SolverSettings` (`engine`, `package_dir`, `python`) is saved as
     `solver.json` in the application data directory;
   - an engine reports `status(settings)` **without loading itself**
     (`importlib` specs and package metadata), and `child_environment(settings)`
     for the analysis child;
   - `OpenSeesPyEngine` is the built-in engine. Its package may live in this
     environment, in another Python of the same minor version
     (`inspect_python` asks that interpreter, isolated, where its `openseespy`
     is), or in any folder;
   - a folder is **appended** to `sys.path` (`activate`): the application's own
     libraries keep precedence, only what it lacks is found there. The child
     receives it in `OPENSEES_STUDIO_ENGINE_PATH`.
3. The analysis CLI (`run.py`) activates that folder first; without OpenSeesPy
   it emits one `error` line saying where to point to one, and exits 2.
4. The GUI disables Run, the batch runs, Check Model Stability and the Material
   Tester when no engine is available, and says why (log, status tip,
   Options → Solver). Everything else works.

## 3. The engine contract

An engine is an object with:

| Member | Meaning |
| --- | --- |
| `key: str` | Saved in `solver.json` (`"openseespy"`). |
| `name: str` | Shown to the user. |
| `case_types: frozenset[str]` | `AnalysisCase.type` values it runs. |
| `status(settings) -> EngineStatus` | Available or not, version, location, message. Must not load the engine. |
| `child_environment(settings) -> dict[str, str]` | Variables the analysis child needs. |
| `create_runner(project, on_progress) -> runner` | In the analysis child: an object whose `run(case, results_dir=...)` returns the results classes of `services.results`. |

Third-party engines register under the `opensees_studio.engines` entry-point
group; one that fails to load is skipped. The analysis child protocol (JSON
lines on stdout, results through `services.result_store`, the exit codes in
`run.py`) is the boundary a second engine must honour.

The parent passes the chosen engine's key in `OPENSEES_STUDIO_ENGINE` (and the
OpenSeesPy folder in `OPENSEES_STUDIO_ENGINE_PATH`, whatever engine solves).
The child builds that engine's runner, refuses up front any case whose type is
not in its `case_types` (one `error` line, exit 2, nothing written), and keeps
the ARPACK re-execution (`core.modal`) for OpenSeesPy only. The stability check
and the Material Tester call OpenSees itself, so they follow OpenSeesPy's own
status rather than the chosen engine's.

## 4. Consequences

- `pip install opensees-studio` is a modeller without a solver; scripts and web
  backends that solve add `[opensees]`.
- Desktop developers keep `pip install -e ".[gui,dev]"`.
- The frozen bundle does not carry OpenSeesPy (`excludes` in the spec). Options →
  Solver downloads it after the user accepts its license
  (`services/engine_install.py`): exactly the two wheels of the platform, at
  URLs, sizes and SHA256 digests pinned in the code, unpacked through a
  `.partial` folder into `<app data>/engines/openseespy-3.8.0.0`, which the
  `package_dir` setting then points at. Linux x86-64, Windows amd64 and macOS
  arm64 are the platforms OpenSeesPy 3.8.0.0 publishes; elsewhere the user
  points to an installation of their own. Moving to another OpenSeesPy
  version means updating `WHEELS` (and the `opensees` extra) together.

## 5. PyNite, the bundled second engine (2026-10-22)

`PyNiteFEA==3.2.0` (MIT) ships in the `gui` extra and in the bundle (with scipy,
about 140 MB). `PyNiteEngine` (`key = "pynite"`, case types `{"Static"}`) runs
`services/pynite_runner.py`: linear static and P-Delta of elastic frames and
trusses, results in OpenSees' layout (DOF order and global signs, frame
`localForce`, truss end forces), each member rolled so PyNite's local axes are
OpenSees' (checked after building). Anything it does not model is refused with
a message rather than approximated. `tests/integration/test_pynite_parity.py`
holds it to OpenSeesPy within 1e-7 of the largest value on 2D and 3D frames and
trusses, and to the closed form for P-Delta.
