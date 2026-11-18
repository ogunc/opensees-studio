"""Member calculation memory: the design checks as a printable document.

The design engine keeps one ``LimitStateCheck`` per limit state and station
(:mod:`core.design.calc`); this module turns them into a document with the
project cover, an index and one sheet per member: properties, demands, every
limit state with its steps, and the governing result. It is a service: it reads
project units, shapes and the report, and writes HTML or Markdown. No Qt.
"""

from __future__ import annotations

import html
import io
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

from opensees_studio import __version__
from opensees_studio.services.steel_design import shape_in_units

Language = Literal["en", "es"]
Format = Literal["html", "markdown", "latex"]

_LABELS: dict[Language, dict[str, str]] = {
    "en": {
        "title": "Calculation Memory",
        "subtitle": "AISC 360-16 steel member checks",
        "project": "Project",
        "author": "Author",
        "company": "Company",
        "date": "Date",
        "program": "Program",
        "revisions": "Revisions",
        "rev": "Rev",
        "by": "By",
        "description": "Description",
        "index": "Index",
        "joints": "Joints (AISC 341-22)",
        "connections": "Connections (AISC 358-22)",
        "zones": "SCBF protected zones (AISC 341-22 F2.5c)",
        "zones_x": "Zones (x/L)",
        "gussets": "SCBF gusset plates (AISC 341-22 F2.6c)",
        "gusset": "Gusset",
        "brace": "Brace",
        "expected": "Ry Fy Ag",
        "brace_connections": "SCBF brace connections (AISC 341-22 F2.6c)",
        "tension": "Tension",
        "compression": "Compression",
        "flexure": "Flexure",
        "weld_leg": "Weld leg",
        "required_leg": "Required leg",
        "weld_ratio": "Weld ratio",
        "weld_status": "Weld status",
        "scbf_joints": "SCBF beam-to-column connections (AISC 341-22 F2.6b)",
        "columns": "Columns",
        "beam_moment": "Beam moment",
        "column_moment": "Column moment",
        "required_moment": "Required moment",
        "available_moment": "Available moment",
        "column_splices": "SCBF column splices (AISC 341-22 F2.6d)",
        "splice": "Splice",
        "top_column": "Top column",
        "bottom_column": "Bottom column",
        "clear_height": "Hc",
        "required_shear": "Required shear",
        "capacity_design": "SCBF capacity design (AISC 341-22 F2.3)",
        "state": "State",
        "analysis_force": "Analysis force",
        "expected_strength": "Expected strength",
        "factor": "Factor",
        "connection": "Connection",
        "rbs_checks": "RBS beam checks (AISC 358-22 5.7 steps 1 and 9)",
        "span_ratio": "Clear span / d",
        "limit": "Limit",
        "span": "Span",
        "shear_demand": "Vh",
        "shear_capacity": "phi Vn",
        "shear_ratio": "Vh / phi Vn",
        "shear": "Shear",
        "web_ratio": "Web ratio",
        "web_status": "Web status",
        "web_connection": "Web connection (AISC 358-22 5.5)",
        "chapter_j": "Connection checks (AISC 360 Chapter J)",
        "name": "Name",
        "type": "Type",
        "nominal": "Nominal",
        "beam": "Beam",
        "column": "Column",
        "protected": "Protected zone",
        "mpr": "Mpr",
        "joint": "Joint",
        "scwb": "Sum M*pc / Sum M*be",
        "panel": "Vr / phi Rn",
        "panel_status": "Panel",
        "element": "Element",
        "shape": "Shape",
        "ratio": "Ratio",
        "status": "Status",
        "properties": "Geometric properties",
        "limit_states": "Limit states",
        "check": "Check",
        "equation": "Equation",
        "demand": "Demand",
        "capacity": "Capacity",
        "steps": "Calculation",
        "label": "Step",
        "formula": "Formula",
        "substitution": "Substitution",
        "value": "Value",
        "governing": "Governing check",
        "load_set": "Load set",
        "station": "Station",
        "notes": "Notes",
        "disclaimer": (
            "This document reproduces the checks run by OpenSees Studio. "
            "The engineer of record remains responsible for the design, the code "
            "edition and the assumptions."
        ),
        "none": "-",
    },
    "es": {
        "title": "Memoria de cálculo",
        "subtitle": "Revisión de elementos de acero AISC 360-16",
        "project": "Proyecto",
        "author": "Autor",
        "company": "Empresa",
        "date": "Fecha",
        "program": "Programa",
        "revisions": "Revisiones",
        "rev": "Rev",
        "by": "Por",
        "description": "Descripción",
        "index": "Índice",
        "joints": "Juntas (AISC 341-22)",
        "connections": "Conexiones (AISC 358-22)",
        "zones": "Zonas protegidas SCBF (AISC 341-22 F2.5c)",
        "zones_x": "Zonas (x/L)",
        "gussets": "Planchas de unión SCBF (AISC 341-22 F2.6c)",
        "gusset": "Plancha",
        "brace": "Arriostramiento",
        "expected": "Ry Fy Ag",
        "brace_connections": "Conexiones de arriostramiento SCBF (AISC 341-22 F2.6c)",
        "tension": "Tracción",
        "compression": "Compresión",
        "flexure": "Flexión",
        "weld_leg": "Pierna de soldadura",
        "required_leg": "Pierna requerida",
        "weld_ratio": "Relación soldadura",
        "weld_status": "Estado soldadura",
        "scbf_joints": "Conexiones viga-columna SCBF (AISC 341-22 F2.6b)",
        "columns": "Columnas",
        "beam_moment": "Momento viga",
        "column_moment": "Momento columna",
        "required_moment": "Momento requerido",
        "available_moment": "Momento disponible",
        "column_splices": "Empalmes de columna SCBF (AISC 341-22 F2.6d)",
        "splice": "Empalme",
        "top_column": "Columna superior",
        "bottom_column": "Columna inferior",
        "clear_height": "Hc",
        "required_shear": "Corte requerido",
        "capacity_design": "Diseño por capacidad SCBF (AISC 341-22 F2.3)",
        "state": "Estado",
        "analysis_force": "Fuerza de análisis",
        "expected_strength": "Resistencia esperada",
        "factor": "Factor",
        "connection": "Conexión",
        "rbs_checks": "Chequeos de viga RBS (AISC 358-22 5.7 pasos 1 y 9)",
        "span_ratio": "Luz libre / d",
        "limit": "Límite",
        "span": "Luz",
        "shear_demand": "Vh",
        "shear_capacity": "phi Vn",
        "shear_ratio": "Vh / phi Vn",
        "shear": "Corte",
        "web_ratio": "Relación alma",
        "web_status": "Estado alma",
        "web_connection": "Conexión del alma (AISC 358-22 5.5)",
        "chapter_j": "Chequeos de conexión (AISC 360 Capítulo J)",
        "name": "Nombre",
        "type": "Tipo",
        "nominal": "Nominal",
        "beam": "Viga",
        "column": "Columna",
        "protected": "Zona protegida",
        "mpr": "Mpr",
        "joint": "Junta",
        "scwb": "Sum M*pc / Sum M*be",
        "panel": "Vr / phi Rn",
        "panel_status": "Panel",
        "element": "Elemento",
        "shape": "Perfil",
        "ratio": "Razón",
        "status": "Estado",
        "properties": "Propiedades geométricas",
        "limit_states": "Estados límite",
        "check": "Chequeo",
        "equation": "Ecuación",
        "demand": "Demanda",
        "capacity": "Capacidad",
        "steps": "Cálculo",
        "label": "Paso",
        "formula": "Fórmula",
        "substitution": "Sustitución",
        "value": "Valor",
        "governing": "Chequeo gobernante",
        "load_set": "Combinación",
        "station": "Estación",
        "notes": "Notas",
        "disclaimer": (
            "Este documento reproduce los chequeos ejecutados por OpenSees Studio. "
            "El ingeniero responsable mantiene la responsabilidad del diseño, la "
            "edición del código y los supuestos."
        ),
        "none": "-",
    },
}

#: Attributes printed, in order, when the shape family has them.
_PROPERTIES = (
    ("A", "A"),
    ("d", "d"),
    ("H", "H"),
    ("B", "B"),
    ("D", "D"),
    ("bf", "bf"),
    ("tf", "tf"),
    ("tw", "tw"),
    ("t", "t"),
    ("Ix", "Ix"),
    ("Iy", "Iy"),
    ("Zx", "Zx"),
    ("Zy", "Zy"),
    ("Sx", "Sx"),
    ("Sy", "Sy"),
    ("rx", "rx"),
    ("ry", "ry"),
    ("J", "J"),
    ("Cw", "Cw"),
)


@dataclass(frozen=True)
class MemoryOptions:
    language: Language = "en"
    fmt: Format = "html"


def _fmt(value: float) -> str:
    if value == 0.0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1e5 or magnitude < 1e-3:
        return f"{value:.4e}"
    return f"{value:.4g}"


def _e(value: object) -> str:
    return html.escape(str(value))


def _properties(shape: object) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for attribute, label in _PROPERTIES:
        value = getattr(shape, attribute, None)
        if isinstance(value, int | float) and value:
            out.append((label, _fmt(float(value))))
    return out


def _member_shape(project: Any, shape_name: str) -> object | None:
    try:
        return shape_in_units(shape_name, project.meta.units)
    except (KeyError, ValueError):
        return None


def _cover(project: Any, labels: dict[str, str]) -> list[tuple[str, str]]:
    meta = project.meta
    return [
        (labels["project"], meta.name),
        (labels["author"], meta.author or labels["none"]),
        (labels["company"], meta.company or labels["none"]),
        (labels["date"], meta.date or labels["none"]),
        (labels["program"], f"OpenSees Studio {__version__}"),
    ]


def _index_rows(report: Any) -> list[list[str]]:
    return [
        [str(m.element_id), m.shape, _fmt(m.ratio), m.status]
        for m in sorted(report.members, key=lambda item: item.element_id)
    ]


def _joint_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(j.node_id),
            _fmt(j.ratio),
            j.status,
            _fmt(j.panel_ratio),
            j.panel_status,
            j.load_set,
        ]
        for j in sorted(report.joints, key=lambda item: item.node_id)
    ]


def _connection_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(c.connection_id),
            str(c.beam_element_id),
            str(c.column_element_id),
            c.shape,
            _fmt(c.sh),
            _fmt(c.mpr),
            f"{c.protected_from:g}-{c.protected_to:g} "
            f"({'clear' if c.zone_clear else 'node inside'})",
            f"{c.flexure_ratio:.3f}" if c.flexure_status else "-",
            c.flexure_status or "-",
            c.status,
        ]
        for c in report.connections
    ]


def _rbs_check_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(c.connection_id),
            _fmt(c.span_ratio) if c.span_limit else "-",
            _fmt(c.span_limit) if c.span_limit else "-",
            c.span_status or "not checked",
            _fmt(c.shear_demand) if c.shear_capacity else "-",
            _fmt(c.shear_capacity) if c.shear_capacity else "-",
            _fmt(c.shear_ratio) if c.shear_capacity else "-",
            c.shear_status or "not checked",
            _fmt(c.web_ratio) if c.web_status else "-",
            c.web_status or "not checked",
        ]
        for c in report.connections
    ]


def _web_check_rows(connection: Any) -> list[list[str]]:
    return [
        [c.name, c.equation, _fmt(c.demand), _fmt(c.capacity), _fmt(c.ratio)]
        for c in connection.web_checks
    ]


def _chapter_j_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(item.check_id),
            item.name or item.check_type,
            item.check_type,
            _fmt(item.demand),
            _fmt(item.nominal),
            _fmt(item.available),
            _fmt(item.ratio),
            item.status,
        ]
        for item in report.chapter_j
    ]


def _protected_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(zone.element_id),
            ", ".join(f"{low:.2f}-{high:.2f}" for low, high in zone.ranges),
            "clear" if zone.zone_clear else "node inside",
        ]
        for zone in report.protected_zones
    ]


def _gusset_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(g.gusset_id),
            str(g.brace_element_id),
            g.shape,
            _fmt(g.t),
            _fmt(g.b),
            _fmt(g.lw),
            _fmt(g.free_length),
            _fmt(g.demand),
            _fmt(g.ratio),
            g.status,
        ]
        for g in report.gussets
    ]


def _brace_connection_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(g.gusset_id),
            str(g.brace_element_id),
            _fmt(g.tension_demand),
            _fmt(g.compression_demand),
            _fmt(g.flexure_demand) if g.flexure_demand else "-",
            _fmt(g.weld_leg) if g.weld_leg else "-",
            _fmt(g.weld_required_leg) if g.weld_leg else "-",
            _fmt(g.weld_ratio) if g.weld_leg else "-",
            g.weld_status or "not checked",
        ]
        for g in report.gussets
    ]


def _scbf_joint_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(j.node_id),
            str(j.beam_element_id),
            ", ".join(str(c) for c in j.column_element_ids),
            str(j.brace_element_id),
            _fmt(j.beam_moment),
            _fmt(j.column_moment),
            _fmt(j.required_moment),
            _fmt(j.available_moment) if j.available_moment else "-",
            _fmt(j.ratio) if j.available_moment else "-",
            j.status,
        ]
        for j in report.scbf_joints
    ]


def _column_splice_rows(report: Any) -> list[list[str]]:
    return [
        [
            str(s.splice_id),
            str(s.node_id),
            f"{s.top_element_id} ({s.shape_top})",
            f"{s.bottom_element_id} ({s.shape_bottom})",
            _fmt(s.clear_height),
            _fmt(s.moment),
            _fmt(s.shear),
            s.status,
        ]
        for s in report.column_splices
    ]


def _capacity_rows(report: Any) -> list[list[str]]:
    return [
        [
            item.load_set,
            str(item.brace_element_id),
            item.shape,
            item.state,
            _fmt(item.analysis_force),
            _fmt(item.expected_force),
            _fmt(item.factor),
        ]
        for item in report.capacity_design
    ]


def _member_html(project: Any, member: Any, labels: dict[str, str]) -> list[str]:
    shape = _member_shape(project, member.shape)
    out = [
        f"<h2>{labels['element']} {member.element_id} - {_e(member.shape)}</h2>",
        f"<p>{labels['governing']}: <b>{_e(member.check)}</b> "
        f"({_e(member.equation)}), {labels['ratio']} {_fmt(member.ratio)}; "
        f"{labels['load_set']} {_e(member.load_set)}; "
        f"{labels['station']} {member.station:.2f}.</p>",
    ]
    if shape is not None:
        rows = _properties(shape)
        if rows:
            out.append(f"<h3>{labels['properties']}</h3>")
            out.append(
                "<table><tr><th>Property</th><th>Value</th></tr>"
                + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in rows)
                + "</table>"
            )
    if member.checks:
        out.append(f"<h3>{labels['limit_states']}</h3>")
        out.append(
            "<table><tr>"
            f"<th>{labels['check']}</th><th>{labels['equation']}</th>"
            f"<th>{labels['demand']}</th><th>{labels['capacity']}</th>"
            f"<th>{labels['ratio']}</th></tr>"
            + "".join(
                f"<tr><td>{_e(c.name)}</td><td>{_e(c.equation)}</td>"
                f"<td>{_fmt(c.demand)}</td><td>{_fmt(c.capacity)}</td>"
                f"<td>{_fmt(c.ratio)}</td></tr>"
                for c in member.checks
            )
            + "</table>"
        )
        for check in member.checks:
            if not check.steps:
                continue
            out.append(f"<h3>{_e(check.name)} - {_e(check.equation)}</h3>")
            out.append(
                "<table><tr>"
                f"<th>{labels['label']}</th><th>{labels['formula']}</th>"
                f"<th>{labels['substitution']}</th><th>{labels['value']}</th></tr>"
                + "".join(
                    f"<tr><td>{_e(s.label)}</td><td>{_e(s.formula)}</td>"
                    f"<td>{_e(s.substitution)}</td>"
                    f"<td>{_fmt(s.value) if s.value is not None else ''}</td></tr>"
                    for s in check.steps
                )
                + "</table>"
            )
    if member.notes:
        out.append(f"<h3>{labels['notes']}</h3><ul>")
        out.extend(f"<li>{_e(note)}</li>" for note in member.notes)
        out.append("</ul>")
    return out


def _html(project: Any, report: Any, labels: dict[str, str]) -> str:
    cover = "".join(
        f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in _cover(project, labels)
    )
    revisions = ""
    if project.meta.revisions:
        revisions = (
            f"<h3>{labels['revisions']}</h3><table><tr>"
            f"<th>{labels['rev']}</th><th>{labels['date']}</th>"
            f"<th>{labels['by']}</th><th>{labels['description']}</th></tr>"
            + "".join(
                f"<tr><td>{_e(r.code)}</td><td>{_e(r.date)}</td>"
                f"<td>{_e(r.by)}</td><td>{_e(r.description)}</td></tr>"
                for r in project.meta.revisions
            )
            + "</table>"
        )
    index = "".join(
        f"<tr><td>{_e(row[0])}</td><td>{_e(row[1])}</td>"
        f"<td>{_e(row[2])}</td><td>{_e(row[3])}</td></tr>"
        for row in _index_rows(report)
    )
    joints = ""
    if report.joints:
        joints = (
            f"<h2>{labels['joints']}</h2><table><tr>"
            f"<th>{labels['joint']}</th><th>{labels['scwb']}</th>"
            f"<th>{labels['status']}</th><th>{labels['panel']}</th>"
            f"<th>{labels['panel_status']}</th><th>{labels['load_set']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _joint_rows(report)
            )
            + "</table>"
        )
    connections_html = ""
    if report.connections:
        connections_html = (
            f"<h2>{labels['connections']}</h2><table><tr>"
            f"<th>{labels['connection']}</th><th>{labels['beam']}</th>"
            f"<th>{labels['column']}</th><th>{labels['shape']}</th>"
            f"<th>Sh</th><th>{labels['mpr']}</th><th>{labels['protected']}</th>"
            f"<th>Mf / phi Mpe</th><th>RBS</th>"
            f"<th>{labels['status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _connection_rows(report)
            )
            + "</table>"
        )
    rbs_checks_html = ""
    if report.connections:
        rbs_checks_html = (
            f"<h2>{labels['rbs_checks']}</h2><table><tr>"
            f"<th>{labels['connection']}</th><th>{labels['span_ratio']}</th>"
            f"<th>{labels['limit']}</th><th>{labels['span']}</th>"
            f"<th>{labels['shear_demand']}</th><th>{labels['shear_capacity']}</th>"
            f"<th>{labels['shear_ratio']}</th><th>{labels['shear']}</th>"
            f"<th>{labels['web_ratio']}</th><th>{labels['web_status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _rbs_check_rows(report)
            )
            + "</table>"
        )
    web_checks_html = ""
    if report.connections:
        web_checks_html = "".join(
            f"<h3>{labels['connection']} {c.connection_id} - "
            f"{labels['web_connection']}</h3><table><tr>"
            f"<th>{labels['check']}</th><th>{labels['equation']}</th>"
            f"<th>{labels['demand']}</th><th>{labels['capacity']}</th>"
            f"<th>{labels['ratio']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _web_check_rows(c)
            )
            + "</table>"
            for c in report.connections
            if c.web_checks
        )
    zones_html = ""
    if report.protected_zones:
        zones_html = (
            f"<h2>{labels['zones']}</h2><table><tr>"
            f"<th>{labels['element']}</th><th>{labels['zones_x']}</th>"
            f"<th>{labels['status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _protected_rows(report)
            )
            + "</table>"
        )
    gussets_html = ""
    if report.gussets:
        gussets_html = (
            f"<h2>{labels['gussets']}</h2><table><tr>"
            f"<th>{labels['gusset']}</th><th>{labels['brace']}</th>"
            f"<th>{labels['shape']}</th><th>t</th><th>b</th><th>Lw</th><th>Lc</th>"
            f"<th>{labels['expected']}</th><th>{labels['ratio']}</th>"
            f"<th>{labels['status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _gusset_rows(report)
            )
            + "</table>"
        )
    brace_connections_html = ""
    if report.gussets:
        brace_connections_html = (
            f"<h2>{labels['brace_connections']}</h2><table><tr>"
            f"<th>{labels['gusset']}</th><th>{labels['brace']}</th>"
            f"<th>{labels['tension']}</th><th>{labels['compression']}</th>"
            f"<th>{labels['flexure']}</th><th>{labels['weld_leg']}</th>"
            f"<th>{labels['required_leg']}</th><th>{labels['weld_ratio']}</th>"
            f"<th>{labels['weld_status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _brace_connection_rows(report)
            )
            + "</table>"
        )
    scbf_joints_html = ""
    if report.scbf_joints:
        scbf_joints_html = (
            f"<h2>{labels['scbf_joints']}</h2><table><tr>"
            f"<th>{labels['joint']}</th><th>{labels['beam']}</th>"
            f"<th>{labels['columns']}</th><th>{labels['brace']}</th>"
            f"<th>{labels['beam_moment']}</th><th>{labels['column_moment']}</th>"
            f"<th>{labels['required_moment']}</th><th>{labels['available_moment']}</th>"
            f"<th>{labels['ratio']}</th><th>{labels['status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _scbf_joint_rows(report)
            )
            + "</table>"
        )
    column_splices_html = ""
    if report.column_splices:
        column_splices_html = (
            f"<h2>{labels['column_splices']}</h2><table><tr>"
            f"<th>{labels['splice']}</th><th>{labels['joint']}</th>"
            f"<th>{labels['top_column']}</th><th>{labels['bottom_column']}</th>"
            f"<th>{labels['clear_height']}</th><th>{labels['required_moment']}</th>"
            f"<th>{labels['required_shear']}</th><th>{labels['status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _column_splice_rows(report)
            )
            + "</table>"
        )
    chapter_j_html = ""
    if report.chapter_j:
        chapter_j_html = (
            f"<h2>{labels['chapter_j']}</h2><table><tr>"
            f"<th>{labels['check']}</th><th>{labels['name']}</th>"
            f"<th>{labels['type']}</th><th>{labels['demand']}</th>"
            f"<th>{labels['nominal']}</th><th>{labels['capacity']}</th>"
            f"<th>{labels['ratio']}</th><th>{labels['status']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _chapter_j_rows(report)
            )
            + "</table>"
        )
        for item in report.chapter_j:
            if not item.steps:
                continue
            chapter_j_html += (
                f"<h3>{labels['check']} {item.check_id} - "
                f"{_e(item.name or item.check_type)}</h3><table><tr>"
                f"<th>{labels['label']}</th><th>{labels['formula']}</th>"
                f"<th>{labels['substitution']}</th><th>{labels['value']}</th></tr>"
                + "".join(
                    f"<tr><td>{_e(step.label)}</td><td>{_e(step.formula)}</td>"
                    f"<td>{_e(step.substitution)}</td>"
                    f"<td>{_fmt(step.value) if step.value is not None else ''}</td></tr>"
                    for step in item.steps
                )
                + "</table>"
            )
    capacity_html = ""
    if report.capacity_design:
        capacity_html = (
            f"<h2>{labels['capacity_design']}</h2><table><tr>"
            f"<th>{labels['load_set']}</th><th>{labels['brace']}</th>"
            f"<th>{labels['shape']}</th><th>{labels['state']}</th>"
            f"<th>{labels['analysis_force']}</th><th>{labels['expected_strength']}</th>"
            f"<th>{labels['factor']}</th></tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
                for row in _capacity_rows(report)
            )
            + "</table>"
        )
    members = []
    for member in sorted(report.members, key=lambda item: item.element_id):
        members.extend(_member_html(project, member, labels))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_e(project.meta.name)} - {_e(labels['title'])}</title>"
        "<style>body{font-family:Arial,sans-serif;font-size:10pt;margin:24px}"
        "h1{font-size:18pt}h2{font-size:14pt;border-bottom:1px solid #888}"
        "h3{font-size:11pt}table{border-collapse:collapse;margin:6px 0 12px}"
        "th,td{border:1px solid #999;padding:1px 4px;text-align:right}"
        "th{background:#eee}td:first-child{text-align:left}"
        "p.note{color:#555;font-style:italic}</style></head><body>"
        f"<h1>{_e(project.meta.name)}</h1>"
        f"<h2>{_e(labels['title'])}</h2><p>{_e(labels['subtitle'])}</p>"
        f"<table>{cover}</table>{revisions}"
        f"<h2>{labels['index']}</h2><table><tr>"
        f"<th>{labels['element']}</th><th>{labels['shape']}</th>"
        f"<th>{labels['ratio']}</th><th>{labels['status']}</th></tr>{index}</table>"
        + joints
        + connections_html
        + rbs_checks_html
        + web_checks_html
        + zones_html
        + gussets_html
        + brace_connections_html
        + scbf_joints_html
        + column_splices_html
        + chapter_j_html
        + capacity_html
        + "".join(members)
        + f"<p class='note'>{_e(labels['disclaimer'])}</p></body></html>"
    )


def _markdown(project: Any, report: Any, labels: dict[str, str]) -> str:
    lines = [f"# {project.meta.name}", "", f"## {labels['title']}", "", labels["subtitle"], ""]
    for key, value in _cover(project, labels):
        lines.append(f"- **{key}:** {value}")
    if project.meta.revisions:
        lines += [
            "",
            f"### {labels['revisions']}",
            "",
            f"| {labels['rev']} | {labels['date']} | {labels['by']} | {labels['description']} |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {r.code} | {r.date} | {r.by} | {r.description} |" for r in project.meta.revisions
        ]
    lines += [
        "",
        f"## {labels['index']}",
        "",
        f"| {labels['element']} | {labels['shape']} | {labels['ratio']} | {labels['status']} |",
        "|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in _index_rows(report)]
    if report.joints:
        lines += [
            "",
            f"## {labels['joints']}",
            "",
            f"| {labels['joint']} | {labels['scwb']} | {labels['status']} | "
            f"{labels['panel']} | {labels['panel_status']} | {labels['load_set']} |",
            "|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _joint_rows(report)]
    if report.connections:
        lines += [
            "",
            f"## {labels['connections']}",
            "",
            f"| {labels['connection']} | {labels['beam']} | {labels['column']} | "
            f"{labels['shape']} | Sh | {labels['mpr']} | {labels['protected']} | "
            f"Mf / phi Mpe | RBS | {labels['status']} |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _connection_rows(report)]
    if report.connections:
        lines += [
            "",
            f"## {labels['rbs_checks']}",
            "",
            f"| {labels['connection']} | {labels['span_ratio']} | {labels['limit']} | "
            f"{labels['span']} | {labels['shear_demand']} | {labels['shear_capacity']} | "
            f"{labels['shear_ratio']} | {labels['shear']} | "
            f"{labels['web_ratio']} | {labels['web_status']} |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _rbs_check_rows(report)]
    for connection in report.connections:
        if not connection.web_checks:
            continue
        lines += [
            "",
            f"### {labels['connection']} {connection.connection_id} - {labels['web_connection']}",
            "",
            f"| {labels['check']} | {labels['equation']} | {labels['demand']} | "
            f"{labels['capacity']} | {labels['ratio']} |",
            "|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _web_check_rows(connection)]
    if report.protected_zones:
        lines += [
            "",
            f"## {labels['zones']}",
            "",
            f"| {labels['element']} | {labels['zones_x']} | {labels['status']} |",
            "|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _protected_rows(report)]
    if report.gussets:
        lines += [
            "",
            f"## {labels['gussets']}",
            "",
            f"| {labels['gusset']} | {labels['brace']} | {labels['shape']} | t | b | Lw | Lc | "
            f"{labels['expected']} | {labels['ratio']} | {labels['status']} |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _gusset_rows(report)]
    if report.gussets:
        lines += [
            "",
            f"## {labels['brace_connections']}",
            "",
            f"| {labels['gusset']} | {labels['brace']} | {labels['tension']} | "
            f"{labels['compression']} | {labels['flexure']} | {labels['weld_leg']} | "
            f"{labels['required_leg']} | {labels['weld_ratio']} | {labels['weld_status']} |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _brace_connection_rows(report)]
    if report.scbf_joints:
        lines += [
            "",
            f"## {labels['scbf_joints']}",
            "",
            f"| {labels['joint']} | {labels['beam']} | {labels['columns']} | "
            f"{labels['brace']} | {labels['beam_moment']} | {labels['column_moment']} | "
            f"{labels['required_moment']} | {labels['available_moment']} | "
            f"{labels['ratio']} | {labels['status']} |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _scbf_joint_rows(report)]
    if report.column_splices:
        lines += [
            "",
            f"## {labels['column_splices']}",
            "",
            f"| {labels['splice']} | {labels['joint']} | {labels['top_column']} | "
            f"{labels['bottom_column']} | {labels['clear_height']} | "
            f"{labels['required_moment']} | {labels['required_shear']} | "
            f"{labels['status']} |",
            "|---|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _column_splice_rows(report)]
    if report.chapter_j:
        lines += [
            "",
            f"## {labels['chapter_j']}",
            "",
            f"| {labels['check']} | {labels['name']} | {labels['type']} | "
            f"{labels['demand']} | {labels['nominal']} | {labels['capacity']} | "
            f"{labels['ratio']} | {labels['status']} |",
            "|---|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _chapter_j_rows(report)]
        for item in report.chapter_j:
            if not item.steps:
                continue
            lines += [
                "",
                f"### {labels['check']} {item.check_id} - {item.name or item.check_type}",
                "",
                f"| {labels['label']} | {labels['formula']} | "
                f"{labels['substitution']} | {labels['value']} |",
                "|---|---|---|---|",
            ]
            lines += [
                f"| {step.label} | {step.formula} | {step.substitution} | "
                f"{_fmt(step.value) if step.value is not None else ''} |"
                for step in item.steps
            ]
    if report.capacity_design:
        lines += [
            "",
            f"## {labels['capacity_design']}",
            "",
            f"| {labels['load_set']} | {labels['brace']} | {labels['shape']} | "
            f"{labels['state']} | {labels['analysis_force']} | "
            f"{labels['expected_strength']} | {labels['factor']} |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in _capacity_rows(report)]
    for member in sorted(report.members, key=lambda item: item.element_id):
        lines += [
            "",
            f"## {labels['element']} {member.element_id} - {member.shape}",
            "",
            f"**{labels['governing']}:** {member.check} ({member.equation}), "
            f"{labels['ratio']} {_fmt(member.ratio)}; {labels['load_set']} "
            f"{member.load_set}; {labels['station']} {member.station:.2f}.",
        ]
        shape = _member_shape(project, member.shape)
        if shape is not None and (props := _properties(shape)):
            lines += ["", f"### {labels['properties']}", "", "| Property | Value |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in props]
        if member.checks:
            lines += [
                "",
                f"### {labels['limit_states']}",
                "",
                f"| {labels['check']} | {labels['equation']} | {labels['demand']} | {labels['capacity']} | {labels['ratio']} |",
                "|---|---|---|---|---|",
            ]
            lines += [
                f"| {c.name} | {c.equation} | {_fmt(c.demand)} | {_fmt(c.capacity)} | {_fmt(c.ratio)} |"
                for c in member.checks
            ]
            for check in member.checks:
                if not check.steps:
                    continue
                lines += [
                    "",
                    f"#### {check.name} - {check.equation}",
                    "",
                    f"| {labels['label']} | {labels['formula']} | {labels['substitution']} | {labels['value']} |",
                    "|---|---|---|---|",
                ]
                lines += [
                    f"| {s.label} | {s.formula} | {s.substitution} | "
                    f"{_fmt(s.value) if s.value is not None else ''} |"
                    for s in check.steps
                ]
        if member.notes:
            lines += ["", f"### {labels['notes']}"]
            lines += [f"- {note}" for note in member.notes]
    lines += ["", "---", labels["disclaimer"], ""]
    return "\n".join(lines)


def build_member_memory(
    project: Any,
    report: Any,
    *,
    language: Language = "en",
    fmt: Format = "html",
) -> str:
    """The member calculation memory as HTML, Markdown or LaTeX."""
    labels = _LABELS.get(language)
    if labels is None:
        raise ValueError(f"Unknown language {language!r}: use 'en' or 'es'.")
    if fmt == "html":
        return _html(project, report, labels)
    if fmt == "markdown":
        return _markdown(project, report, labels)
    if fmt == "latex":
        return _latex(project, report, labels)
    raise ValueError(f"Unknown format {fmt!r}: use 'html', 'markdown' or 'latex'.")


def _tex_escape(value: object) -> str:
    text = str(value)
    for old, new in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ):
        text = text.replace(old, new)
    return text


def _latex(project: Any, report: Any, labels: dict[str, str]) -> str:
    lines = [
        r"\documentclass[10pt]{article}",
        r"\usepackage[margin=20mm]{geometry}",
        r"\usepackage{longtable,booktabs}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[utf8]{inputenc}",
        r"\begin{document}",
        rf"\section*{{{_tex_escape(project.meta.name)}}}",
        rf"\subsection*{{{_tex_escape(labels['title'])}}}",
        _tex_escape(labels["subtitle"]),
        "",
    ]
    for key, value in _cover(project, labels):
        lines.append(rf"\textbf{{{_tex_escape(key)}:}} {_tex_escape(value)}\\")
    if project.meta.revisions:
        lines += [
            "",
            rf"\subsection*{{{_tex_escape(labels['revisions'])}}}",
            r"\begin{longtable}{llll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['rev'])} & {_tex_escape(labels['date'])} & "
            rf"{_tex_escape(labels['by'])} & {_tex_escape(labels['description'])} \\ \toprule"
        )
        lines += [
            rf"{_tex_escape(r.code)} & {_tex_escape(r.date)} & "
            rf"{_tex_escape(r.by)} & {_tex_escape(r.description)} \\"
            for r in project.meta.revisions
        ]
        lines.append(r"\end{longtable}")
    lines += ["", rf"\subsection*{{{_tex_escape(labels['index'])}}}", r"\begin{longtable}{llll}"]
    lines.append(
        rf"{_tex_escape(labels['element'])} & {_tex_escape(labels['shape'])} & "
        rf"{_tex_escape(labels['ratio'])} & {_tex_escape(labels['status'])} \\ \toprule"
    )
    lines += [" & ".join(_tex_escape(cell) for cell in row) + r" \\" for row in _index_rows(report)]
    lines.append(r"\end{longtable}")
    if report.joints:
        lines += [rf"\subsection*{{{_tex_escape(labels['joints'])}}}", r"\begin{longtable}{llllll}"]
        lines.append(
            rf"{_tex_escape(labels['joint'])} & {_tex_escape(labels['scwb'])} & "
            rf"{_tex_escape(labels['status'])} & {_tex_escape(labels['panel'])} & "
            rf"{_tex_escape(labels['panel_status'])} & {_tex_escape(labels['load_set'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\" for row in _joint_rows(report)
        ]
        lines.append(r"\end{longtable}")
    if report.connections:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['connections'])}}}",
            r"\begin{longtable}{llllllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['connection'])} & {_tex_escape(labels['beam'])} & "
            rf"{_tex_escape(labels['column'])} & {_tex_escape(labels['shape'])} & Sh & "
            rf"{_tex_escape(labels['mpr'])} & {_tex_escape(labels['protected'])} & "
            rf"Mf / phi Mpe & RBS & {_tex_escape(labels['status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _connection_rows(report)
        ]
        lines.append(r"\end{longtable}")
    if report.connections:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['rbs_checks'])}}}",
            r"\begin{longtable}{llllllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['connection'])} & {_tex_escape(labels['span_ratio'])} & "
            rf"{_tex_escape(labels['limit'])} & {_tex_escape(labels['span'])} & "
            rf"{_tex_escape(labels['shear_demand'])} & {_tex_escape(labels['shear_capacity'])} & "
            rf"{_tex_escape(labels['shear_ratio'])} & {_tex_escape(labels['shear'])} & "
            rf"{_tex_escape(labels['web_ratio'])} & {_tex_escape(labels['web_status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _rbs_check_rows(report)
        ]
        lines.append(r"\end{longtable}")
    for connection in report.connections:
        if not connection.web_checks:
            continue
        lines += [
            rf"\subsection*{{{_tex_escape(labels['connection'])} "
            rf"{connection.connection_id} - {_tex_escape(labels['web_connection'])}}}",
            r"\begin{longtable}{lllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['check'])} & {_tex_escape(labels['equation'])} & "
            rf"{_tex_escape(labels['demand'])} & {_tex_escape(labels['capacity'])} & "
            rf"{_tex_escape(labels['ratio'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _web_check_rows(connection)
        ]
        lines.append(r"\end{longtable}")
    if report.protected_zones:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['zones'])}}}",
            r"\begin{longtable}{lll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['element'])} & {_tex_escape(labels['zones_x'])} & "
            rf"{_tex_escape(labels['status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _protected_rows(report)
        ]
        lines.append(r"\end{longtable}")
    if report.gussets:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['gussets'])}}}",
            r"\begin{longtable}{llllllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['gusset'])} & {_tex_escape(labels['brace'])} & "
            rf"{_tex_escape(labels['shape'])} & t & b & Lw & Lc & "
            rf"{_tex_escape(labels['expected'])} & {_tex_escape(labels['ratio'])} & "
            rf"{_tex_escape(labels['status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\" for row in _gusset_rows(report)
        ]
        lines.append(r"\end{longtable}")
    if report.gussets:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['brace_connections'])}}}",
            r"\begin{longtable}{lllllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['gusset'])} & {_tex_escape(labels['brace'])} & "
            rf"{_tex_escape(labels['tension'])} & {_tex_escape(labels['compression'])} & "
            rf"{_tex_escape(labels['flexure'])} & {_tex_escape(labels['weld_leg'])} & "
            rf"{_tex_escape(labels['required_leg'])} & {_tex_escape(labels['weld_ratio'])} & "
            rf"{_tex_escape(labels['weld_status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _brace_connection_rows(report)
        ]
        lines.append(r"\end{longtable}")
    if report.scbf_joints:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['scbf_joints'])}}}",
            r"\begin{longtable}{llllllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['joint'])} & {_tex_escape(labels['beam'])} & "
            rf"{_tex_escape(labels['columns'])} & {_tex_escape(labels['brace'])} & "
            rf"{_tex_escape(labels['beam_moment'])} & {_tex_escape(labels['column_moment'])} & "
            rf"{_tex_escape(labels['required_moment'])} & {_tex_escape(labels['available_moment'])} & "
            rf"{_tex_escape(labels['ratio'])} & {_tex_escape(labels['status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _scbf_joint_rows(report)
        ]
        lines.append(r"\end{longtable}")
    if report.column_splices:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['column_splices'])}}}",
            r"\begin{longtable}{llllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['splice'])} & {_tex_escape(labels['joint'])} & "
            rf"{_tex_escape(labels['top_column'])} & {_tex_escape(labels['bottom_column'])} & "
            rf"{_tex_escape(labels['clear_height'])} & {_tex_escape(labels['required_moment'])} & "
            rf"{_tex_escape(labels['required_shear'])} & {_tex_escape(labels['status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _column_splice_rows(report)
        ]
        lines.append(r"\end{longtable}")
    if report.chapter_j:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['chapter_j'])}}}",
            r"\begin{longtable}{llllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['check'])} & {_tex_escape(labels['name'])} & "
            rf"{_tex_escape(labels['type'])} & {_tex_escape(labels['demand'])} & "
            rf"{_tex_escape(labels['nominal'])} & {_tex_escape(labels['capacity'])} & "
            rf"{_tex_escape(labels['ratio'])} & {_tex_escape(labels['status'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\"
            for row in _chapter_j_rows(report)
        ]
        lines.append(r"\end{longtable}")
        for item in report.chapter_j:
            if not item.steps:
                continue
            lines += [
                rf"\subsection*{{{_tex_escape(labels['check'])} {item.check_id} - "
                rf"{_tex_escape(item.name or item.check_type)}}}",
                r"\begin{longtable}{llll}",
            ]
            lines.append(
                rf"{_tex_escape(labels['label'])} & {_tex_escape(labels['formula'])} & "
                rf"{_tex_escape(labels['substitution'])} & "
                rf"{_tex_escape(labels['value'])} \\ \toprule"
            )
            lines += [
                " & ".join(_tex_escape(str(cell)) for cell in row) + r" \\"
                for row in (
                    [
                        step.label,
                        step.formula,
                        step.substitution,
                        _fmt(step.value) if step.value is not None else "",
                    ]
                    for step in item.steps
                )
            ]
            lines.append(r"\end{longtable}")
    if report.capacity_design:
        lines += [
            rf"\subsection*{{{_tex_escape(labels['capacity_design'])}}}",
            r"\begin{longtable}{lllllll}",
        ]
        lines.append(
            rf"{_tex_escape(labels['load_set'])} & {_tex_escape(labels['brace'])} & "
            rf"{_tex_escape(labels['shape'])} & {_tex_escape(labels['state'])} & "
            rf"{_tex_escape(labels['analysis_force'])} & "
            rf"{_tex_escape(labels['expected_strength'])} & "
            rf"{_tex_escape(labels['factor'])} \\ \toprule"
        )
        lines += [
            " & ".join(_tex_escape(cell) for cell in row) + r" \\" for row in _capacity_rows(report)
        ]
        lines.append(r"\end{longtable}")
    for member in sorted(report.members, key=lambda item: item.element_id):
        lines += [
            "",
            rf"\subsection*{{{_tex_escape(labels['element'])} {member.element_id} - {_tex_escape(member.shape)}}}",
            rf"\textbf{{{_tex_escape(labels['governing'])}:}} {_tex_escape(member.check)} "
            rf"({_tex_escape(member.equation)}), {_tex_escape(labels['ratio'])} {_fmt(member.ratio)}; "
            rf"{_tex_escape(labels['load_set'])} {_tex_escape(member.load_set)}; "
            rf"{_tex_escape(labels['station'])} {member.station:.2f}.",
            "",
        ]
        shape = _member_shape(project, member.shape)
        if shape is not None and (props := _properties(shape)):
            lines += [rf"\textbf{{{_tex_escape(labels['properties'])}}}", r"\begin{longtable}{ll}"]
            lines += [rf"{_tex_escape(k)} & {_tex_escape(v)} \\" for k, v in props]
            lines.append(r"\end{longtable}")
        for check in member.checks:
            lines += [
                rf"\textbf{{{_tex_escape(check.name)}}} ({_tex_escape(check.equation)}): "
                rf"{_tex_escape(labels['demand'])} {_fmt(check.demand)}, "
                rf"{_tex_escape(labels['capacity'])} {_fmt(check.capacity)}, "
                rf"{_tex_escape(labels['ratio'])} {_fmt(check.ratio)}.",
            ]
            if check.steps:
                lines += [r"\begin{longtable}{llll}"]
                lines.append(
                    rf"{_tex_escape(labels['label'])} & {_tex_escape(labels['formula'])} & "
                    rf"{_tex_escape(labels['substitution'])} & {_tex_escape(labels['value'])} \\ \toprule"
                )
                lines += [
                    rf"{_tex_escape(s.label)} & {_tex_escape(s.formula)} & "
                    rf"{_tex_escape(s.substitution)} & "
                    rf"{_fmt(s.value) if s.value is not None else ''} \\"
                    for s in check.steps
                ]
                lines.append(r"\end{longtable}")
    lines += ["", r"\emph{" + _tex_escape(labels["disclaimer"]) + "}", r"\end{document}", ""]
    return "\n".join(lines)


def _odt_text(value: object) -> str:
    import xml.sax.saxutils as saxutils

    return saxutils.escape(str(value))


def odt_bytes(project: Any, report: Any, *, language: Language = "en") -> bytes:
    """The member memory as an OpenDocument text package (a zip)."""
    labels = _LABELS.get(language)
    if labels is None:
        raise ValueError(f"Unknown language {language!r}: use 'en' or 'es'.")
    body: list[str] = [
        f"<text:h text:outline-level='1'>{_odt_text(project.meta.name)}</text:h>",
        f"<text:h text:outline-level='2'>{_odt_text(labels['title'])}</text:h>",
        f"<text:p>{_odt_text(labels['subtitle'])}</text:p>",
    ]
    for key, value in _cover(project, labels):
        body.append(
            f"<text:p><text:span text:style-name='Bold'>{_odt_text(key)}:</text:span> {_odt_text(value)}</text:p>"
        )
    if project.meta.revisions:
        body.append(f"<text:h text:outline-level='3'>{_odt_text(labels['revisions'])}</text:h>")
        body.append("<table:table table:name='Revisions'>")
        for row in [[labels["rev"], labels["date"], labels["by"], labels["description"]]] + [
            [r.code, r.date, r.by, r.description] for r in project.meta.revisions
        ]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['index'])}</text:h>")
    body.append("<table:table table:name='Index'>")
    index_rows = [[labels["element"], labels["shape"], labels["ratio"], labels["status"]]]
    index_rows.extend(_index_rows(report))
    for row in index_rows:
        body.append(
            "<table:table-row>"
            + "".join(
                f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>" for c in row
            )
            + "</table:table-row>"
        )
    body.append("</table:table>")
    if report.joints:
        body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['joints'])}</text:h>")
        body.append("<table:table table:name='Joints'>")
        header = [
            labels["joint"],
            labels["scwb"],
            labels["status"],
            labels["panel"],
            labels["panel_status"],
            labels["load_set"],
        ]
        for row in [header, *_joint_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.connections:
        body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['connections'])}</text:h>")
        body.append("<table:table table:name='Connections'>")
        header = [
            labels["connection"],
            labels["beam"],
            labels["column"],
            labels["shape"],
            "Sh",
            labels["mpr"],
            labels["protected"],
            "Mf / phi Mpe",
            "RBS",
            labels["status"],
        ]
        for row in [header, *_connection_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.connections:
        body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['rbs_checks'])}</text:h>")
        body.append("<table:table table:name='RbsChecks'>")
        header = [
            labels["connection"],
            labels["span_ratio"],
            labels["limit"],
            labels["span"],
            labels["shear_demand"],
            labels["shear_capacity"],
            labels["shear_ratio"],
            labels["shear"],
            labels["web_ratio"],
            labels["web_status"],
        ]
        for row in [header, *_rbs_check_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    for connection in report.connections:
        if not connection.web_checks:
            continue
        body.append(
            f"<text:h text:outline-level='2'>{_odt_text(labels['connection'])} "
            f"{connection.connection_id} - "
            f"{_odt_text(labels['web_connection'])}</text:h>"
        )
        body.append("<table:table table:name='WebChecks'>")
        header = [
            labels["check"],
            labels["equation"],
            labels["demand"],
            labels["capacity"],
            labels["ratio"],
        ]
        for row in [header, *_web_check_rows(connection)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.protected_zones:
        body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['zones'])}</text:h>")
        body.append("<table:table table:name='Zones'>")
        header = [labels["element"], labels["zones_x"], labels["status"]]
        for row in [header, *_protected_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.gussets:
        body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['gussets'])}</text:h>")
        body.append("<table:table table:name='Gussets'>")
        header = [
            labels["gusset"],
            labels["brace"],
            labels["shape"],
            "t",
            "b",
            "Lw",
            "Lc",
            labels["expected"],
            labels["ratio"],
            labels["status"],
        ]
        for row in [header, *_gusset_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.gussets:
        body.append(
            f"<text:h text:outline-level='2'>{_odt_text(labels['brace_connections'])}</text:h>"
        )
        body.append("<table:table table:name='BraceConnections'>")
        header = [
            labels["gusset"],
            labels["brace"],
            labels["tension"],
            labels["compression"],
            labels["flexure"],
            labels["weld_leg"],
            labels["required_leg"],
            labels["weld_ratio"],
            labels["weld_status"],
        ]
        for row in [header, *_brace_connection_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.scbf_joints:
        body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['scbf_joints'])}</text:h>")
        body.append("<table:table table:name='ScbfJoints'>")
        header = [
            labels["joint"],
            labels["beam"],
            labels["columns"],
            labels["brace"],
            labels["beam_moment"],
            labels["column_moment"],
            labels["required_moment"],
            labels["available_moment"],
            labels["ratio"],
            labels["status"],
        ]
        for row in [header, *_scbf_joint_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.column_splices:
        body.append(
            f"<text:h text:outline-level='2'>{_odt_text(labels['column_splices'])}</text:h>"
        )
        body.append("<table:table table:name='ColumnSplices'>")
        header = [
            labels["splice"],
            labels["joint"],
            labels["top_column"],
            labels["bottom_column"],
            labels["clear_height"],
            labels["required_moment"],
            labels["required_shear"],
            labels["status"],
        ]
        for row in [header, *_column_splice_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    if report.chapter_j:
        body.append(f"<text:h text:outline-level='2'>{_odt_text(labels['chapter_j'])}</text:h>")
        body.append("<table:table table:name='ChapterJ'>")
        header = [
            labels["check"],
            labels["name"],
            labels["type"],
            labels["demand"],
            labels["nominal"],
            labels["capacity"],
            labels["ratio"],
            labels["status"],
        ]
        for row in [header, *_chapter_j_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
        for item in report.chapter_j:
            if not item.steps:
                continue
            body.append(
                f"<text:h text:outline-level='2'>{_odt_text(labels['check'])} "
                f"{item.check_id} - {_odt_text(item.name or item.check_type)}</text:h>"
            )
            body.append("<table:table table:name='ChapterJSteps'>")
            header = [
                labels["label"],
                labels["formula"],
                labels["substitution"],
                labels["value"],
            ]
            rows = [
                [
                    step.label,
                    step.formula,
                    step.substitution,
                    _fmt(step.value) if step.value is not None else "",
                ]
                for step in item.steps
            ]
            for row in [header, *rows]:
                body.append(
                    "<table:table-row>"
                    + "".join(
                        f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                        for c in row
                    )
                    + "</table:table-row>"
                )
            body.append("</table:table>")
    if report.capacity_design:
        body.append(
            f"<text:h text:outline-level='2'>{_odt_text(labels['capacity_design'])}</text:h>"
        )
        body.append("<table:table table:name='Capacity'>")
        header = [
            labels["load_set"],
            labels["brace"],
            labels["shape"],
            labels["state"],
            labels["analysis_force"],
            labels["expected_strength"],
            labels["factor"],
        ]
        for row in [header, *_capacity_rows(report)]:
            body.append(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
            )
        body.append("</table:table>")
    for member in sorted(report.members, key=lambda item: item.element_id):
        body.append(
            f"<text:h text:outline-level='2'>{_odt_text(labels['element'])} {member.element_id} - {_odt_text(member.shape)}</text:h>"
        )
        body.append(
            f"<text:p>{_odt_text(labels['governing'])}: {_odt_text(member.check)} ({_odt_text(member.equation)}); {_odt_text(labels['ratio'])} {_fmt(member.ratio)}</text:p>"
        )
        shape = _member_shape(project, member.shape)
        if shape is not None and (props := _properties(shape)):
            body.append(
                f"<text:h text:outline-level='3'>{_odt_text(labels['properties'])}</text:h>"
            )
            body.append("<table:table table:name='Properties'>")
            for key, value in props:
                body.append(
                    f"<table:table-row><table:table-cell><text:p>{_odt_text(key)}</text:p></table:table-cell><table:table-cell><text:p>{_odt_text(value)}</text:p></table:table-cell></table:table-row>"
                )
            body.append("</table:table>")
        if member.checks:
            body.append(
                f"<text:h text:outline-level='3'>{_odt_text(labels['limit_states'])}</text:h>"
            )
            body.append("<table:table table:name='Checks'>")
            header = [
                labels["check"],
                labels["equation"],
                labels["demand"],
                labels["capacity"],
                labels["ratio"],
            ]
            rows = [header] + [
                [c.name, c.equation, _fmt(c.demand), _fmt(c.capacity), _fmt(c.ratio)]
                for c in member.checks
            ]
            for row in rows:
                body.append(
                    "<table:table-row>"
                    + "".join(
                        f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                        for c in row
                    )
                    + "</table:table-row>"
                )
            body.append("</table:table>")
            for check in member.checks:
                if not check.steps:
                    continue
                body.append(
                    f"<text:h text:outline-level='4'>{_odt_text(check.name)} - {_odt_text(check.equation)}</text:h>"
                )
                body.append("<table:table table:name='Steps'>")
                header = [
                    labels["label"],
                    labels["formula"],
                    labels["substitution"],
                    labels["value"],
                ]
                rows = [header] + [
                    [
                        s.label,
                        s.formula,
                        s.substitution,
                        _fmt(s.value) if s.value is not None else "",
                    ]
                    for s in check.steps
                ]
                for row in rows:
                    body.append(
                        "<table:table-row>"
                        + "".join(
                            f"<table:table-cell><text:p>{_odt_text(c)}</text:p></table:table-cell>"
                            for c in row
                        )
                        + "</table:table-row>"
                    )
                body.append("</table:table>")
    body.append(
        f"<text:p><text:span text:style-name='Italic'>{_odt_text(labels['disclaimer'])}</text:span></text:p>"
    )
    content = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<office:document-content "
        "xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0' "
        "xmlns:text='urn:oasis:names:tc:opendocument:xmlns:text:1.0' "
        "xmlns:table='urn:oasis:names:tc:opendocument:xmlns:table:1.0' "
        "office:version='1.2'><office:body><office:text>"
        + "".join(body)
        + "</office:text></office:body></office:document-content>"
    )
    styles = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<office:document-styles "
        "xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0' "
        "xmlns:text='urn:oasis:names:tc:opendocument:xmlns:text:1.0' "
        "xmlns:style='urn:oasis:names:tc:opendocument:xmlns:style:1.0' "
        "office:version='1.2'><office:styles>"
        "<style:style style:name='Bold' style:family='text'><style:text-properties fo:font-weight='bold' xmlns:fo='urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0'/></style:style>"
        "<style:style style:name='Italic' style:family='text'><style:text-properties fo:font-style='italic' xmlns:fo='urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0'/></style:style>"
        "</office:styles></office:document-styles>"
    )
    manifest = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<manifest:manifest xmlns:manifest='urn:oasis:names:tc:opendocument:xmlns:manifest:1.0' manifest:version='1.2'>"
        "<manifest:file-entry manifest:full-path='/' manifest:media-type='application/vnd.oasis.opendocument.text'/>"
        "<manifest:file-entry manifest:full-path='content.xml' manifest:media-type='text/xml'/>"
        "<manifest:file-entry manifest:full-path='styles.xml' manifest:media-type='text/xml'/>"
        "</manifest:manifest>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "mimetype",
            "application/vnd.oasis.opendocument.text",
            compress_type=zipfile.ZIP_STORED,
        )
        package.writestr("content.xml", content)
        package.writestr("styles.xml", styles)
        package.writestr("META-INF/manifest.xml", manifest)
    return buffer.getvalue()
