#!/usr/bin/env python3
"""Validador de la biblioteca de skills.

Comprueba el contrato de cada ``SKILL.md`` (frontmatter, nombre, secciones y
tamaño) y, opcionalmente, regenera ``skills/index.json``.

Sin dependencias externas: solo biblioteca estándar.

Uso:
    python skills/scripts/validate_skills.py
    python skills/scripts/validate_skills.py --index
    python skills/scripts/validate_skills.py --quiet

Salida: 0 si todo es válido; 1 si hay errores.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TRACKS = ("core", "seismic", "codes", "design", "platform", "github", "interop")
STATUSES = ("ready", "draft", "stub")
REQUIRED_SECTIONS = (
    "Cuándo usar esta skill",
    "Alcance y límites",
    "Entradas y supuestos",
    "Fundamento y formulación",
    "Procedimiento",
    "Implementación en la plataforma",
    "Datos normativos",
    "Verificación y casos de prueba",
    "Errores frecuentes y trampas",
    "Interfaz de salida",
    "Referencias",
    "Registro de verificación",
)
MIN_LINES = 100
WARN_LINES = 120
DESC_MIN = 120
DESC_MAX = 1024

ROOT = Path(__file__).resolve().parent.parent
SKILL_GLOB = "[!_]*/*/SKILL.md"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], int]:
    """Parser mínimo del frontmatter YAML usado por la biblioteca."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("no empieza con '---'")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("frontmatter sin cierre '---'")

    block = lines[1:end]
    data: dict[str, Any] = {}
    i = 0
    while i < len(block):
        line = block[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            raise ValueError(f"línea de frontmatter no reconocida: {line!r}")
        key, raw = m.group(1), m.group(2).strip()
        if raw in (">-", ">", "|", "|-", ""):
            chunk: list[str] = []
            i += 1
            while i < len(block) and (block[i].startswith(" ") or not block[i].strip()):
                chunk.append(block[i])
                i += 1
            if key == "metadata":
                data[key] = _parse_nested(chunk)
            else:
                data[key] = " ".join(s.strip() for s in chunk if s.strip())
            continue
        if raw.startswith("[") and raw.endswith("]"):
            data[key] = [v.strip().strip("'\"") for v in raw[1:-1].split(",") if v.strip()]
        else:
            data[key] = raw.strip("'\"")
        i += 1
    return data, end + 1


def _parse_nested(lines: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in lines:
        if not line.strip():
            continue
        m = re.match(r"^\s+([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            out[key] = [v.strip().strip("'\"") for v in raw[1:-1].split(",") if v.strip()]
        else:
            out[key] = raw.strip("'\"")
    return out


def check_skill(path: Path, text: str) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {}

    rel = path.relative_to(ROOT)
    track = rel.parts[0]
    dirname = rel.parts[1]

    try:
        fm, _ = parse_frontmatter(text)
    except ValueError as exc:
        return [f"{rel}: frontmatter inválido: {exc}"], warnings, info

    name = fm.get("name", "")
    if name != dirname:
        errors.append(f"{rel}: name '{name}' != directorio '{dirname}'")

    description = fm.get("description", "")
    if len(description) < DESC_MIN:
        errors.append(f"{rel}: description demasiado corta ({len(description)} < {DESC_MIN})")
    if len(description) > DESC_MAX:
        errors.append(f"{rel}: description demasiado larga ({len(description)} > {DESC_MAX})")

    meta = fm.get("metadata") or {}
    if not isinstance(meta, dict):
        errors.append(f"{rel}: metadata no es un mapa")
        meta = {}
    if meta.get("track") not in TRACKS:
        errors.append(f"{rel}: metadata.track inválido: {meta.get('track')!r}")
    elif meta.get("track") != track:
        errors.append(
            f"{rel}: metadata.track '{meta.get('track')}' != carpeta '{track}'"
        )
    if meta.get("status") not in STATUSES:
        errors.append(f"{rel}: metadata.status inválido: {meta.get('status')!r}")
    for key in ("jurisdiction", "edition", "verified_on", "scope"):
        if not meta.get(key):
            errors.append(f"{rel}: falta metadata.{key}")

    headings = re.findall(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
    for section in REQUIRED_SECTIONS:
        if section not in headings:
            errors.append(f"{rel}: falta la sección '## {section}'")

    n_lines = text.count("\n") + 1
    if n_lines < MIN_LINES:
        errors.append(f"{rel}: contenido demasiado corto ({n_lines} < {MIN_LINES} líneas)")
    elif n_lines < WARN_LINES:
        warnings.append(f"{rel}: contenido justo ({n_lines} líneas)")

    if meta.get("status") == "ready" and "VERIFICAR" in text:
        errors.append(f"{rel}: status 'ready' pero contiene marcas VERIFICAR")

    info = {
        "name": name,
        "track": track,
        "path": str(rel.parent),
        "description": description,
        "jurisdiction": meta.get("jurisdiction", ""),
        "edition": meta.get("edition", ""),
        "status": meta.get("status", ""),
        "verified_on": meta.get("verified_on", ""),
        "scope": meta.get("scope", []),
        "lines": n_lines,
        "open_verifications": text.count("VERIFICAR"),
    }
    return errors, warnings, info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Valida la biblioteca de skills.")
    ap.add_argument("--index", action="store_true", help="regenera skills/index.json")
    ap.add_argument("--quiet", action="store_true", help="solo errores y resumen")
    args = ap.parse_args(argv)

    paths = sorted(ROOT.glob(SKILL_GLOB))
    if not paths:
        print(f"ERROR: no se encontró ningún SKILL.md en {ROOT}", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    all_warnings: list[str] = []
    index: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for path in paths:
        text = path.read_text(encoding="utf-8")
        errors, warnings, info = check_skill(path, text)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        if info.get("name"):
            if info["name"] in seen:
                all_errors.append(
                    f"{info['path']}: name duplicado con {seen[info['name']]}"
                )
            seen[info["name"]] = info["path"]
            index.append(info)

    for warning in all_warnings:
        if not args.quiet:
            print(f"aviso: {warning}")
    for error in all_errors:
        print(f"ERROR: {error}")

    if args.index and not all_errors:
        payload = {
            "generated_by": "skills/scripts/validate_skills.py",
            "count": len(index),
            "tracks": {
                track: sorted(i["name"] for i in index if i["track"] == track)
                for track in TRACKS
            },
            "skills": sorted(index, key=lambda i: (i["track"], i["name"])),
        }
        (ROOT / "index.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not args.quiet:
            print(f"index.json regenerado con {len(index)} skills")

    print(
        f"\n{len(paths)} skills · {len(all_errors)} errores · "
        f"{len(all_warnings)} avisos · "
        f"{sum(1 for i in index if i['status'] == 'ready')} listas"
    )
    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
