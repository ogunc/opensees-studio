"""Auto-infrastructure defaults shared by the desktop GUI and headless callers.

The app deliberately removes hard ordering dependencies so a user can "draw and
run" without first opening a library dialog:

* drawing a frame ensures a default :class:`ElasticSection`,
* drawing a truss ensures a default :class:`ElasticUniaxial` material,
* applying a load ensures a default ``LinearTimeSeries`` + ``PlainLoadPattern``.

That "create-if-missing" convenience used to live in the Qt tool/command layer,
which forced every headless consumer (the web backend, scripts, notebooks) to
re-implement the exact default values and risk drift. This module is the single
source of truth. It is Qt-free and openseespy-free, like the rest of ``core``.

Two layers are provided:

* ``find_*`` / ``make_*`` — non-mutating helpers. ``find_*`` locates an existing
  default-eligible entity; ``make_*`` builds a fresh one with the canonical
  values. The desktop tools/commands use these so their own *undoable* inserts
  stay responsible for adding the entity to the project (preserving undo/redo).
* ``ensure_*`` — convenience wrappers that find-or-create **and append in place**,
  returning the entity. These are for headless callers with no undo stack; they
  mutate ``project`` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.core.loads import (
    ConstantTimeSeries,
    LinearTimeSeries,
    PlainLoadPattern,
    TimeSeries,
)
from opensees_studio.core.materials import ElasticUniaxial
from opensees_studio.core.sections import ElasticSection

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

# Default truss bar area (m²) — 10 cm² nominal.
DEFAULT_TRUSS_AREA = 0.001

# Default name for an auto-created time series + load pattern pair.
DEFAULT_PATTERN_NAME = "Default"


# ── factories (build with canonical values; do NOT mutate the project) ───────
def make_default_section(section_id: int) -> ElasticSection:
    """Build the canonical default elastic frame section (used when none exists)."""
    return ElasticSection(
        id=section_id,
        name="Default Section",
        E=200e9,
        A=0.01,
        Iz=8.33e-6,
        Iy=8.33e-6,
        G=80e9,
        J=1e-6,
    )


def make_default_truss_material(material_id: int) -> ElasticUniaxial:
    """Build the canonical default uniaxial steel for truss bars."""
    return ElasticUniaxial(
        id=material_id,
        name="DEFAULT-Truss-Steel",
        E=200e9,  # Pa — typical structural steel
    )


def make_default_time_series(
    ts_id: int, *, kind: str = "Linear", name: str = DEFAULT_PATTERN_NAME
) -> TimeSeries:
    """Build the canonical auto-created time series.

    ``kind="Constant"`` yields a :class:`ConstantTimeSeries` (for constant axial
    preloads); anything else yields a :class:`LinearTimeSeries` (the ramping
    default), matching the desktop load commands.
    """
    ts_cls = ConstantTimeSeries if kind == "Constant" else LinearTimeSeries
    return ts_cls(id=ts_id, name=name)


def make_default_pattern(
    pattern_id: int, time_series_id: int, *, name: str = DEFAULT_PATTERN_NAME
) -> PlainLoadPattern:
    """Build the canonical auto-created plain load pattern."""
    return PlainLoadPattern(id=pattern_id, name=name, time_series_id=time_series_id)


# ── finders (locate an existing default-eligible entity) ─────────────────────
def find_default_section(project: Project) -> ElasticSection | None:
    """Return the first :class:`ElasticSection` in the project, if any."""
    for sec in project.sections:
        if isinstance(sec, ElasticSection):
            return sec
    return None


def find_default_truss_material(project: Project) -> ElasticUniaxial | None:
    """Return the first :class:`ElasticUniaxial` material in the project, if any."""
    for mat in project.materials:
        if isinstance(mat, ElasticUniaxial):
            return mat
    return None


def find_plain_pattern(project: Project) -> PlainLoadPattern | None:
    """Return the first :class:`PlainLoadPattern` in the project, if any."""
    for pat in project.load_patterns:
        if isinstance(pat, PlainLoadPattern):
            return pat
    return None


# ── ensure (find-or-create AND append in place; headless / no undo) ──────────
def ensure_default_section(project: Project) -> ElasticSection:
    """Return the project's default section, appending a fresh one if absent.

    Mutates ``project`` in place — for headless callers (web backend, scripts)
    that have no undo stack. The desktop instead uses :func:`find_default_section`
    + :func:`make_default_section` so its undoable command performs the insert.
    """
    existing = find_default_section(project)
    if existing is not None:
        return existing
    section = make_default_section(project.next_section_id())
    project.sections.append(section)
    return section


def ensure_default_truss_material(project: Project) -> ElasticUniaxial:
    """Return the project's default truss material, appending one if absent.

    Mutates ``project`` in place (headless use; see :func:`ensure_default_section`).
    """
    existing = find_default_truss_material(project)
    if existing is not None:
        return existing
    mat = make_default_truss_material(project.next_material_id())
    project.materials.append(mat)
    return mat


def ensure_default_timeseries_and_pattern(
    project: Project, *, name: str | None = None, ts_kind: str = "Linear"
) -> PlainLoadPattern:
    """Return a plain load pattern, creating a time-series + pattern pair if needed.

    With ``name=None`` an existing plain pattern is reused; with a name, a fresh
    named pair is always created (mirrors the desktop load commands, which let a
    user stack several named patterns). Mutates ``project`` in place (headless use;
    see :func:`ensure_default_section`).
    """
    if name is None:
        existing = find_plain_pattern(project)
        if existing is not None:
            return existing
    pattern_name = name or DEFAULT_PATTERN_NAME
    ts = make_default_time_series(
        project.next_time_series_id(), kind=ts_kind, name=pattern_name
    )
    project.time_series.append(ts)
    pattern = make_default_pattern(
        project.next_pattern_id(), ts.id, name=pattern_name
    )
    project.load_patterns.append(pattern)
    return pattern
