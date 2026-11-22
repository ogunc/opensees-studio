"""The report in Spanish: a translation of the words the report prints.

The report body is built in English (:mod:`services.report`); this module
rewrites its *text* — never tags, attributes or the embedded drawing — through
an exact-phrase table and a short list of patterns for the phrases that carry
numbers or names ("Results — DEAD", "Storey drift — limit 0.02, …"). A column
heading with a unit ("Elevation [m]") is translated without its unit.

What the table does not know stays in English, so a section added to the
report later still prints, untranslated, until its phrases are added to
:data:`SPANISH`. User data (case, pattern, section and material names) is not
in the table and is never translated.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable

SPANISH: dict[str, str] = {
    # layout
    "Calculation report": "Reporte de cálculo",
    "Contents": "Índice",
    "Page {page} of {pages}": "Página {page} de {pages}",
    "Every section is left out of this report.": "Todas las secciones quedaron fuera del reporte.",
    # project block
    "Field": "Campo",
    "Value": "Valor",
    "Author": "Autor",
    "Company": "Empresa",
    "Date": "Fecha",
    "Units": "Unidades",
    "Model": "Modelo",
    "Program": "Programa",
    "Revisions": "Revisiones",
    "Rev": "Rev",
    "By": "Por",
    "Description": "Descripción",
    # model chapters
    "Item": "Elemento",
    "Count": "Cantidad",
    "Joints": "Nodos",
    "Supported joints": "Nodos con apoyo",
    "Materials": "Materiales",
    "Sections": "Secciones",
    "Load patterns": "Patrones de carga",
    "Analysis cases": "Casos de análisis",
    "Load combinations": "Combinaciones de carga",
    "Storeys": "Pisos",
    "Groups": "Grupos",
    "Section cuts": "Cortes de sección",
    "ID": "ID",
    "Name": "Nombre",
    "Type": "Tipo",
    "Values": "Valores",
    "None.": "Ninguno.",
    "Self weight": "Peso propio",
    "Loads": "Cargas",
    "ΣFx joint": "ΣFx nodal",
    "ΣFy joint": "ΣFy nodal",
    "ΣFz joint": "ΣFz nodal",
    "Patterns": "Patrones",
    "Terms": "Términos",
    # results
    "Results": "Resultados",
    "No results for the model as it is now: run the cases before exporting the report.": (
        "No hay resultados para el modelo tal como está: corré los casos antes de "
        "exportar el reporte."
    ),
    "Peak displacements (final step)": "Desplazamientos máximos (último paso)",
    "Peak combined displacements": "Desplazamientos combinados máximos",
    "Final-step reactions": "Reacciones del último paso",
    "Reactions": "Reacciones",
    "Component": "Componente",
    "Peak": "Máximo",
    "At": "En",
    "Node": "Nodo",
    "Sum": "Suma",
    "Step": "Paso",
    "Time": "Tiempo",
    "Mode": "Modo",
    "Eigenvalue": "Valor propio",
    "Mass ratio": "Fracción de masa",
    "Modal results": "Resultados modales",
    "Modal contributions": "Contribuciones modales",
    "Storey mode shapes": "Formas modales por piso",
    "Storey response (final step)": "Respuesta por piso (último paso)",
    "Storey response (CQC peaks)": "Respuesta por piso (máximos CQC)",
    "Storey response (SRSS peaks)": "Respuesta por piso (máximos SRSS)",
    "Storey": "Piso",
    "Elevation": "Elevación",
    "Height": "Altura",
    "Drift X": "Deriva X",
    "Drift Y": "Deriva Y",
    "Shear X": "Corte X",
    "Shear Y": "Corte Y",
    "Base shear": "Corte basal",
    "Base": "Base",
    "Mode shapes as OpenSees normalises them; shears need a spectrum.": (
        "Formas modales con la normalización de OpenSees; los cortes requieren un espectro."
    ),
    # design
    "Setting": "Parámetro",
    "Method": "Método",
    "Ratio limit": "Relación límite",
    "Seismic system": "Sistema sísmico",
    "Load sets": "Conjuntos de carga",
    "Load set": "Conjunto de carga",
    "Element": "Elemento",
    "Shape": "Perfil",
    "Ratio": "Relación",
    "Capacity": "Capacidad",
    "Status": "Estado",
    "Governs": "Controla",
    "Equation": "Ecuación",
    "Station": "Estación",
    "Drift ratio": "Deriva",
    "Ratio to limit": "Relación con el límite",
    "P-M interaction": "Interacción P-M",
    "on": "sí",
    "off": "no",
    "none": "ninguno",
    "not designed": "no diseñado",
    "not checked": "no verificado",
    "Joint": "Nodo",
    "Panel": "Panel",
    "Continuity": "Continuidad",
    "Columns": "Columnas",
    "Beams": "Vigas",
    "Connection": "Conexión",
    "Beam": "Viga",
    "Column": "Columna",
    "Protected zone": "Zona protegida",
    "Span": "Luz",
    "Shear": "Corte",
    "Web ratio": "Relación del alma",
    "Web status": "Estado del alma",
    "Check": "Verificación",
    "Demand": "Demanda",
    "Nominal": "Nominal",
    "Available": "Disponible",
    "Required": "Requerido",
    "Brace": "Riostra",
    "State": "Estado",
    "Analysis force": "Fuerza de análisis",
    "Expected strength": "Resistencia esperada",
    "Factor": "Factor",
    "Gusset": "Cartela",
    "Tension": "Tracción",
    "Compression": "Compresión",
    "Flexure": "Flexión",
    "Weld leg": "Cateto de soldadura",
    "Required leg": "Cateto requerido",
    "Weld ratio": "Relación de soldadura",
    "Weld status": "Estado de soldadura",
    "Splice": "Empalme",
    "Top column": "Columna superior",
    "Bottom column": "Columna inferior",
    "Required moment": "Momento requerido",
    "Required shear": "Corte requerido",
    "Beam moment": "Momento de viga",
    "Column moment": "Momento de columna",
    "Zones (x/L)": "Zonas (x/L)",
    "clear": "libre",
    "node inside": "nodo dentro",
    "Steel frame check — AISC 360-16": "Verificación de pórticos de acero — AISC 360-16",
    "Strong-column/weak-beam and panel zone (AISC 341-22 E3.4a, AISC 360-22 J10.6)": (
        "Columna fuerte/viga débil y zona de panel (AISC 341-22 E3.4a, AISC 360-22 J10.6)"
    ),
    "Connections (AISC 358-22)": "Conexiones (AISC 358-22)",
    "RBS beam checks (AISC 358-22 5.7 steps 1 and 9)": (
        "Verificaciones de viga RBS (AISC 358-22 5.7 pasos 1 y 9)"
    ),
    "RBS web connection (AISC 358-22 5.5)": "Conexión del alma RBS (AISC 358-22 5.5)",
    "SCBF protected zones (AISC 341-22 F2.5c)": "Zonas protegidas SCBF (AISC 341-22 F2.5c)",
    "SCBF gusset plates (AISC 341-22 F2.6c)": "Cartelas SCBF (AISC 341-22 F2.6c)",
    "SCBF brace connections (AISC 341-22 F2.6c)": (
        "Conexiones de riostras SCBF (AISC 341-22 F2.6c)"
    ),
    "SCBF capacity design (AISC 341-22 F2.3)": "Diseño por capacidad SCBF (AISC 341-22 F2.3)",
    "SCBF beam-to-column connections (AISC 341-22 F2.6b)": (
        "Conexiones viga-columna SCBF (AISC 341-22 F2.6b)"
    ),
    "SCBF column splices (AISC 341-22 F2.6d)": "Empalmes de columna SCBF (AISC 341-22 F2.6d)",
    "Connection checks (AISC 360 Chapter J)": (
        "Verificaciones de conexiones (AISC 360 Capítulo J)"
    ),
}
"""English phrase → Spanish, matched on a whole text run (or a heading without its unit)."""

_PATTERNS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    (re.compile(r"^Results — (.+)$"), r"Resultados — \1"),
    (re.compile(r"^Elements: (.+)$"), r"Elementos: \1"),
    (re.compile(r"^(\d)D, (\d+) DOF per joint \(Z up\)$"), r"\1D, \2 GDL por nodo (Z arriba)"),
    (re.compile(r"^Pushover curve \(node (\d+)\)$"), r"Curva pushover (nodo \1)"),
    (re.compile(r"^Transient: (\d+) steps, dt = (.+)$"), r"Transitorio: \1 pasos, dt = \2"),
    (
        re.compile(
            r"^(\d+) more row\(s\) left out; export the full table from the Results panel \(CSV\)\.$"
        ),
        r"\1 fila(s) más omitida(s); exportá la tabla completa desde el panel de resultados (CSV).",
    ),
    (
        re.compile(r"^Storey drift — limit (.+), amplification (.+)$"),
        r"Deriva de piso — límite \1, amplificación \2",
    ),
    (re.compile(r"^(\d+) frame member\(s\) not designed\.$"), r"\1 barra(s) sin diseñar."),
    (
        re.compile(
            r"^(\d+) member\(s\) checked, (\d+) over the limit, (\d+) not designed"
            r"(?:; largest ratio ([\d.]+) \(element (\d+)\))?(.*)$"
        ),
        lambda m: (
            f"{m.group(1)} barra(s) verificada(s), {m.group(2)} sobre el límite, "
            f"{m.group(3)} sin diseñar"
            + (f"; mayor relación {m.group(4)} (elemento {m.group(5)})" if m.group(4) else "")
            + m.group(6)
        ),
    ),
]

_WORDS = re.compile(r"\b(\d+) (joint|member|area|imposed)\b")
_WORD_ES = {
    "joint": "nodal(es)",
    "member": "en barras",
    "area": "de área",
    "imposed": "impuesta(s)",
}
_LIST_PREFIX = re.compile(r"\b(Combination|Case|case)\b")
_LIST_ES = {"Combination": "Combinación", "Case": "Caso", "case": "caso"}
_UNIT = re.compile(r"^(.+?) (\[[^\]]*\])$")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)?\xa0\xa0)(.+)$", re.DOTALL)
"""A numbered heading or contents row ("2.1  Peaks"): the number stays, the title is translated."""
_PAREN = re.compile(r"^(.+) \((supports)\)$")


def _phrase(text: str) -> str:
    if text in SPANISH:
        return SPANISH[text]
    for pattern, repl in _PATTERNS:
        if pattern.match(text):
            return pattern.sub(repl, text)
    unit = _UNIT.match(text)
    if unit and unit.group(1) in SPANISH:
        return f"{SPANISH[unit.group(1)]} {unit.group(2)}"
    paren = _PAREN.match(text)
    if paren:
        return f"{_phrase(paren.group(1))} (apoyos)"
    if _WORDS.search(text):
        return _WORDS.sub(lambda m: f"{m.group(1)} {_WORD_ES[m.group(2)]}", text)
    if _LIST_PREFIX.search(text) and ("'" in text or "Combination " in text or "Case " in text):
        return _LIST_PREFIX.sub(lambda m: _LIST_ES[m.group(1)], text)
    return text


def translate(text: str, language: str = "en") -> str:
    """One phrase in ``language`` (unchanged in English or when the table does not know it)."""
    if language != "es":
        return text
    stripped = text.strip()
    if not stripped:
        return text
    numbered = _NUMBERED.match(stripped)
    out = numbered.group(1) + _phrase(numbered.group(2)) if numbered else _phrase(stripped)
    return text.replace(stripped, out) if out != stripped else text


_TEXT = re.compile(r"(<style\b.*?</style>)|>([^<>]+)<", re.DOTALL | re.IGNORECASE)


def translate_html(page: str, language: str = "en") -> str:
    """``page`` with every text run between tags translated; tags and styles untouched."""
    if language != "es":
        return page

    def run(match: re.Match[str]) -> str:
        if match.group(1):
            return match.group(1)
        raw = match.group(2)
        text = html.unescape(raw)
        out = translate(text, language)
        return match.group(0) if out == text else f">{html.escape(out, quote=False)}<"

    return _TEXT.sub(run, page)
