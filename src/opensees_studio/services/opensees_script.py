"""Export a project as a plain OpenSeesPy script.

The GUI never writes Tcl or Python by hand: :class:`OpenSeesRunner` translates
the model into ``ops.*`` calls and executes them. This module reuses that
translator with a recorder standing in for OpenSeesPy, so the exported script
is **the same command sequence the solver would be given** — not a second
implementation that can drift from it.

What the script contains:

- the model, exactly what :meth:`OpenSeesRunner.build` emits;
- when a case is selected, the case's patterns, its analysis setup
  (system, numberer, constraints, test, algorithm, integrator, and Rayleigh
  damping) and its step protocol, recorded by dry-running the case.

Everything that only *reads* results (``nodeDisp``, ``eleForce``, …) is left
out: the script builds and runs the model, it does not harvest diagrams.

The transient case is the one that cannot be dry-run: its run writes recorder
files and reads them back, which a recorder standing in for OpenSees cannot
produce. Its setup is recorded the same way and its step loop is written from
the case's own ``n_steps``; ``tests/integration/test_script_parity.py`` runs
the generated script and compares the numbers with the runner's.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from opensees_studio.core import Project
from opensees_studio.core.analysis import TransientCase
from opensees_studio.services.opensees_runner import OpenSeesRunner

#: Calls that read results. They are part of a run, not of a model script, and
#: the recorder answers them with benign values so the runner's extraction code
#: can finish.
READ_ONLY_CALLS = frozenset(
    {
        "nodeDisp",
        "nodeReaction",
        "nodeVel",
        "nodeAccel",
        "nodeEigenvector",
        "nodeDOFs",
        "eleForce",
        "eleResponse",
        "eleNodes",
        "getTime",
        "getNodeTags",
        "getEleTags",
        "version",
    }
)

_HEADER = '''"""OpenSees model exported by OpenSees Studio {version}.

{provenance}

This is plain OpenSeesPy: ``python {filename}`` builds the model{and_runs}.
It is the same command sequence the application gives the solver, with the
result extraction removed.
"""

import openseespy.opensees as ops

'''


def _literal(value: Any) -> str:
    """A Python literal for ``value``, including NumPy scalars and arrays."""
    if isinstance(value, np.ndarray):
        return "[" + ", ".join(_literal(v) for v in value.tolist()) + "]"
    if isinstance(value, np.generic):
        return _literal(value.item())
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    return repr(value)


class _CallRecorder:
    """Stands in for ``openseespy.opensees`` and records calls as source lines.

    Anything in :data:`READ_ONLY_CALLS` is answered instead of recorded:
    ``analyze`` reports success so the runner's step loop runs to the end, an
    ``eigen`` call returns the right number of eigenvalues, and the result
    readers return zeros.
    """

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def _call(*args: Any, **kwargs: Any) -> Any:
            if name not in READ_ONLY_CALLS:
                rendered = ", ".join(
                    [
                        *(_literal(a) for a in args),
                        *(f"{k}={_literal(v)}" for k, v in kwargs.items()),
                    ]
                )
                self.lines.append(f"ops.{name}({rendered})")
            return _return_value(name, args)

        return _call


def _return_value(name: str, args: tuple[Any, ...]) -> Any:
    """What a read-only or control call has to return for the runner to go on."""
    if name == "analyze":
        return 0  # "converged": the step loop has to run to the end
    if name == "eigen":
        modes = next((a for a in reversed(args) if isinstance(a, int)), 1)
        return [1.0] * modes
    if name in ("eleForce", "eleResponse"):
        return []
    if name in READ_ONLY_CALLS:
        return 0.0
    return None


def _analysis_block(project: Project, case: Any) -> list[str]:
    """The recorded analysis commands for ``case``, transient included."""
    recorder = _CallRecorder()
    runner = OpenSeesRunner(project, ops_module=recorder)

    if isinstance(case, TransientCase):
        # Cannot be dry-run (see the module docstring): record the setup and
        # write the step loop from the case's own numbers.
        runner._emit_patterns_for_case(case.pattern_ids)
        runner._setup_analysis(case)
        # ``analyze(1)`` alone is ambiguous for a transient analysis — OpenSees
        # rejects it with "insufficient args: analyze numIncr deltaT" — so the
        # step carries the case's dt, exactly as ``_run_transient_staged`` does.
        return [
            *recorder.lines,
            f"for _step in range({case.n_steps}):",
            f"    ops.analyze(1, {_literal(case.dt)})",
        ]

    # ``run`` builds the model first, so the analysis part is everything after
    # the model's own line count (the build is deterministic).
    model_lines = len(_record_model(project))
    runner.run(case)
    return recorder.lines[model_lines:]


def _record_model(project: Project) -> list[str]:
    """The model commands, exactly what ``build()`` emits."""
    recorder = _CallRecorder()
    OpenSeesRunner(project, ops_module=recorder).build()
    return recorder.lines


def case_label(case: Any) -> str:
    """``#3 Transient 'Sine-Gust-2s'`` — how a case is named in the UI."""
    return f"#{case.id} {case.type} {case.name!r}"


def export_script(
    project: Project,
    case: Any | None = None,
    *,
    version: str = "",
    filename: str = "model.py",
) -> str:
    """Return ``project`` as a runnable OpenSeesPy script.

    Args:
        project: The model to export.
        case: An analysis case to append, or None for the model alone.
        version: Application version for the provenance header.
        filename: Name to suggest in the header's run instructions.

    Returns:
        The script source, ending in a newline.
    """
    model_lines = _record_model(project)
    lines = list(model_lines)

    if case is not None:
        block = _analysis_block(project, case)
        lines += [
            "",
            # ASCII only: the script is downloaded, opened in whatever editor
            # the user has and written by tools whose default encoding on
            # Windows is cp1252 — a box-drawing rule here made `write_text`
            # raise UnicodeEncodeError there (CI, Windows, 2026-10-10).
            f"# --- Analysis: case {case_label(case)} ---",
            "# Setup and step protocol as the application runs them.",
            *block,
        ]

    meta = project.meta
    units = getattr(getattr(meta, "units", None), "value", None) or "as modelled"
    provenance = "\n".join(
        [
            f"Project: {meta.name or '(unnamed)'}",
            f"Units:   {units}",
            f"Model:   {len(project.nodes)} nodes, {len(project.elements)} elements, "
            f"ndm={project.ndm}, ndf={project.ndf}",
            f"Case:    {case_label(case) if case is not None else 'model only'}",
        ]
    )
    header = _HEADER.format(
        version=version or "(unknown version)",
        provenance=provenance,
        filename=filename,
        and_runs=" and runs the case above" if case is not None else "",
    )
    return header + "\n".join(lines) + "\n"
