"""Model and results report as one self-contained HTML page (File → Export → Report).

The page reads top to bottom like a calculation report: the project, the model
in numbers, materials and sections, load patterns, analysis cases and
combinations, then the results the session has for the model as it is now, and
— when the project carries design settings (Design → Steel Frame Check) — the
AISC 360-16 member check and the storey drift check over those results.
Results reuse the Results panel's tables (:mod:`services.result_tables`), so the
units and signs are the ones the panel shows; long tables are summarised (peak
displacement per DOF, reactions of the supports only) rather than printed node
by node.

The view saves the HTML as is or prints it to PDF with Qt. No Qt here.
"""

from __future__ import annotations

import datetime as _dt
import html
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from opensees_studio import __version__
from opensees_studio.core import PlainLoadPattern, Project
from opensees_studio.core.combinations import term_label
from opensees_studio.services.result_tables import (
    ResultTable,
    display_text,
    modal_tables,
    pushover_tables,
    response_spectrum_tables,
    section_cut_table,
    static_tables,
    storey_table,
)
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.steel_design import (
    default_fy,
    default_load_sets,
    load_set_label,
    steel_frame_check,
    storey_drift_check,
)

DIGITS = 5
MAX_ROWS = 60
"""A table longer than this is cut, with a note saying how many rows were left out."""

_STYLE = """
body { font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #111; margin: 24px; }
h1 { font-size: 18pt; margin-bottom: 2px; }
h2 { font-size: 13pt; border-bottom: 1px solid #888; margin-top: 22px; }
h3 { font-size: 11pt; margin-bottom: 4px; }
table { border-collapse: collapse; margin: 6px 0 12px 0; }
th, td { border: 1px solid #999; padding: 1px 4px; text-align: right; white-space: nowrap;
         font-size: 7.5pt; }
th { background: #e8e8e8; }
td.text, th.text { text-align: left; }
p.note { color: #555; font-style: italic; margin: 2px 0; }
"""


def _e(value: object) -> str:
    return html.escape(str(value))


def _table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def cell(tag: str, value: Any) -> str:
        cls = (
            ' class="text"' if not isinstance(value, int | float) or isinstance(value, bool) else ""
        )
        text = display_text(value, DIGITS) if isinstance(value, float) else str(value)
        return f"<{tag}{cls}>{_e(text)}</{tag}>"

    head = "".join(f'<th class="text">{_e(c)}</th>' for c in columns)
    body = "".join("<tr>" + "".join(cell("td", v) for v in row) + "</tr>" for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


CHOP = 1e-9
"""A value below this fraction of the table's largest magnitude prints as 0 (solver noise)."""


def _chopped(rows: Sequence[Sequence[Any]]) -> list[list[Any]]:
    """Rows with round-off noise (1e-13 next to 1e+4) set to 0."""
    out = [list(row) for row in rows]
    numbers = [abs(v) for row in out for v in row if isinstance(v, float)]
    floor = CHOP * max(numbers, default=0.0)
    return [[0.0 if isinstance(v, float) and abs(v) < floor else v for v in row] for row in out]


def _result_table(table: ResultTable) -> str:
    out = [f"<h3>{_e(table.title)}</h3>"]
    out += [f'<p class="note">{_e(n)}</p>' for n in table.notes]
    rows = _chopped(table.rows[:MAX_ROWS])
    out.append(_table(table.columns, rows))
    if len(table.rows) > MAX_ROWS:
        out.append(
            f'<p class="note">{len(table.rows) - MAX_ROWS} more row(s) left out; '
            "export the full table from the Results panel (CSV).</p>"
        )
    return "".join(out)


def _peaks(table: ResultTable, title: str) -> ResultTable:
    """One row per numeric column: the largest magnitude and the row (node) it is at."""
    peak = ResultTable(title, ["Component", "Peak", "At"])
    for c, column in enumerate(table.columns[1:], start=1):
        values = [(row[c], row[0]) for row in table.rows if isinstance(row[c], int | float)]
        if values:
            value, where = max(values, key=lambda v: abs(float(v[0])))
            peak.rows.append([column, float(value), where])
    return peak


def _supports_only(table: ResultTable, project: Project) -> ResultTable:
    restrained = {n.id for n in project.nodes if any(n.restraint)}
    rows = [row for row in table.rows if row and row[0] in restrained]
    sums = ["Sum"] + [
        float(sum(float(row[c]) for row in rows)) for c in range(1, len(table.columns))
    ]
    return ResultTable(table.title + " (supports)", table.columns, [*rows, sums], table.notes)


# ─────────────────────────── model sections ───────────────────────────
def _model_summary(project: Project) -> str:
    types = Counter(e.type for e in project.elements)
    rows: list[list[Any]] = [
        ["Joints", len(project.nodes)],
        ["Supported joints", sum(1 for n in project.nodes if any(n.restraint))],
        *([f"Elements: {t}", n] for t, n in sorted(types.items())),
        ["Materials", len(project.materials)],
        ["Sections", len(project.sections)],
        ["Load patterns", len(project.load_patterns)],
        ["Analysis cases", len(project.analyses)],
        ["Load combinations", len(project.combinations)],
        ["Storeys", len(project.storeys)],
        ["Groups", len(project.groups)],
        ["Section cuts", len(project.section_cuts)],
    ]
    return _table(["Item", "Count"], rows)


def _properties(items: Sequence[Any]) -> str:
    rows = []
    for item in items:
        data = item.model_dump(exclude={"id", "name", "type"})
        values = ", ".join(
            f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
            for k, v in data.items()
            if isinstance(v, int | float | str) and not isinstance(v, bool)
        )
        rows.append([item.id, item.name, getattr(item, "type", type(item).__name__), values])
    return _table(["ID", "Name", "Type", "Values"], rows) if rows else "<p>None.</p>"


def _patterns(project: Project) -> str:
    rows = []
    for p in project.load_patterns:
        if isinstance(p, PlainLoadPattern):
            counts = (
                ("joint", len(p.nodal_loads)),
                (
                    "member",
                    len(p.element_loads)
                    + len(p.distributed_loads)
                    + len(p.point_loads)
                    + len(p.temperature_loads),
                ),
                ("area", len(p.surface_loads) + len(p.floor_loads)),
                ("imposed", len(p.imposed_displacements)),
            )
            loads = ", ".join(f"{n} {kind}" for kind, n in counts if n) or "—"
            total = [sum(load.forces[k] for load in p.nodal_loads) for k in range(3)]
            rows.append(
                [p.id, p.name, p.type, f"{p.self_weight:g}", loads] + [float(v) for v in total]
            )
        else:
            rows.append([p.id, p.name, p.type, "", "", "", "", ""])
    return (
        _table(
            ["ID", "Name", "Type", "Self weight", "Loads", "ΣFx joint", "ΣFy joint", "ΣFz joint"],
            rows,
        )
        if rows
        else "<p>None.</p>"
    )


def _cases(project: Project) -> str:
    rows = [
        [c.id, c.name, c.type, ", ".join(map(str, getattr(c, "pattern_ids", [])))]
        for c in project.analyses
    ]
    return _table(["ID", "Name", "Type", "Patterns"], rows) if rows else "<p>None.</p>"


def _combinations(project: Project) -> str:
    rows = [
        [
            combo.id,
            combo.name,
            combo.combination_type,
            " + ".join(f"{t.factor:g} × {term_label(project, t)}" for t in combo.terms),
        ]
        for combo in project.combinations
    ]
    return _table(["ID", "Name", "Type", "Terms"], rows) if rows else "<p>None.</p>"


# ─────────────────────────── design ───────────────────────────
def _design_section(project: Project, results: Mapping[int, Any]) -> str:
    """The steel member check and the drift check, with the stored design settings."""
    settings = project.design
    if settings is None:
        return ""
    fy = settings.fy if settings.fy is not None else default_fy(project.meta.units)
    load_sets = settings.load_sets or default_load_sets(project)
    out = [
        "<h2>Steel frame check — AISC 360-16</h2>",
        _table(
            ["Setting", "Value"],
            [
                ["Method", settings.method],
                ["Fy", fy],
                ["Ratio limit", settings.ratio_limit],
                ["Load sets", ", ".join(load_set_label(project, ls) for ls in load_sets) or "—"],
            ],
        ),
    ]
    report = steel_frame_check(project, results, settings)
    out.append(f"<p>{_e(report.summary())}</p>")
    out += [f"<p class='note'>{_e(note)}</p>" for note in report.notes]
    designed = sorted(
        (m for m in report.members if m.status != "not designed"), key=lambda m: -m.ratio
    )
    if designed:
        rows = [
            [m.element_id, m.shape, m.ratio, m.status, m.check, m.equation, m.load_set]
            for m in designed
        ]
        out.append(
            _table(
                ["Element", "Shape", "Ratio", "Status", "Governs", "Equation", "Load set"],
                rows,
            )
        )
    skipped = len(report.members) - len(designed)
    if skipped:
        out.append(f"<p class='note'>{skipped} frame member(s) not designed.</p>")

    drift_rows: list[list[Any]] = []
    for result in sorted(results.values(), key=lambda r: getattr(r, "case_id", 0)):
        drift = storey_drift_check(project, result, settings)
        if drift is None:
            continue
        drift_rows += [
            [drift.load_set, row.storey, max(row.drift, default=0.0), row.ratio]
            for row in drift.rows
        ]
    if drift_rows:
        out.append(
            f"<h3>Storey drift — limit {settings.drift_limit:g}, "
            f"amplification {settings.drift_amplification:g}</h3>"
        )
        out.append(_table(["Load set", "Storey", "Drift ratio", "Ratio to limit"], drift_rows))
    return "".join(out)


# ─────────────────────────── results ───────────────────────────
def _results_section(results: Any, project: Project) -> str:
    name = getattr(results, "case_name", "") or f"case {getattr(results, 'case_id', '?')}"
    out = [f"<h2>Results — {_e(name)}</h2>"]
    tables: list[ResultTable] = []
    if isinstance(results, StaticResults):
        disp, reactions, _forces = static_tables(results, project)
        tables += [
            _peaks(disp, "Peak displacements (final step)"),
            _supports_only(reactions, project),
        ]
    elif isinstance(results, PushoverResults):
        curve, disp, _forces = pushover_tables(results, project)
        tables += [curve, _peaks(disp, "Peak displacements (final step)")]
    elif isinstance(results, ModalResults):
        tables += modal_tables(results)
    elif isinstance(results, ResponseSpectrumResults):
        combined, *rest = response_spectrum_tables(results, project)
        tables += [_peaks(combined, "Peak combined displacements"), rest[-1]]
    elif isinstance(results, TransientResults):
        out.append(f"<p>Transient: {_e(results.steps_summary())}, dt = {results.dt:g} s.</p>")
    else:
        out.append(f"<p>{_e(type(results).__name__)} is not part of the report.</p>")
    for extra in (storey_table(results, project), section_cut_table(results, project)):
        if extra is not None:
            tables.append(extra)
    out += [_result_table(t) for t in tables]
    return "".join(out)


def build_report(
    project: Project,
    results: Mapping[int, Any] | Sequence[Any] = (),
    *,
    now: _dt.datetime | None = None,
) -> str:
    """The report page: the model, then each result in ``results`` (by case id order)."""
    meta = project.meta
    stamp = (now or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    items = list(results.values()) if isinstance(results, Mapping) else list(results)
    items.sort(key=lambda r: getattr(r, "case_id", 0))
    units = meta.units.value if hasattr(meta.units, "value") else str(meta.units)
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{_e(meta.name)} — report</title><style>{_STYLE}</style></head><body>",
        f"<h1>{_e(meta.name)}</h1>",
        f"<p>{_e(meta.description)}</p>" if meta.description else "",
        _table(
            ["Field", "Value"],
            [
                ["Author", meta.author or "—"],
                ["Date", stamp],
                ["Units", units],
                ["Model", f"{project.ndm}D, {project.ndf} DOF per joint (Z up)"],
                ["Program", f"OpenSees Studio {__version__}"],
            ],
        ),
        "<h2>Model</h2>",
        _model_summary(project),
        "<h2>Materials</h2>",
        _properties(project.materials),
        "<h2>Sections</h2>",
        _properties(project.sections),
        "<h2>Load patterns</h2>",
        _patterns(project),
        "<h2>Analysis cases</h2>",
        _cases(project),
        "<h2>Load combinations</h2>",
        _combinations(project),
    ]
    if not items:
        parts.append(
            "<h2>Results</h2><p>No results for the model as it is now: run the cases "
            "before exporting the report.</p>"
        )
    parts += [_results_section(r, project) for r in items]
    parts.append(
        _design_section(project, {getattr(r, "case_id", k): r for k, r in enumerate(items)})
    )
    parts.append("</body></html>")
    return "".join(parts)
