"""Build the vendored AISC v16 shape table from the steelpy distribution.

The application ships a compact CSV of section properties instead of depending
on the publishing package: the data is static, and `steelpy` pulls pandas and
openpyxl in for what is, here, a one-time read.

Source of truth: `steelpy` (Apache-2.0), whose shape files state that the
values are those of the AISC Steel Construction Manual, 16th edition, in US
customary units (in, in², in⁴, in⁶, lb/ft).

Usage::

    pip download --no-deps --dest /tmp/steelpy steelpy
    python -c "import zipfile; zipfile.ZipFile('/tmp/steelpy/steelpy-*.whl').extractall('/tmp/steelpy')"
    python tools/build_aisc_data.py --source /tmp/steelpy/steelpy/"shape files"

The output is committed, so CI never needs the source. `tests/unit/test_aisc.py`
checks the table's internal consistency, and
`tests/integration/test_aisc_sections.py` inserts shapes into a model and
compares the response with a hand-built section of the same properties.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

#: family → (source file, column mapping). ``None`` means "absent in this family".
#: `d`/`bf`/`tw`/`tf` are the I-shape fields; for an angle `b` is the leg width
#: and `t` its thickness; for a tube, `od`/`tnom`.
FAMILIES: dict[str, tuple[str, dict[str, str]]] = {
    "W": (
        "W_shapes.csv",
        {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"},
    ),
    "HP": ("HP_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    "M": ("M_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    "S": ("S_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    "C": ("C_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    "MC": ("MC_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    "WT": ("WT_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    "MT": ("MT_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    "ST": ("ST_shapes.csv", {"d": "d", "bf": "bf", "tw": "tw", "tf": "tf"}),
    # An angle's legs: d along one leg, b along the other, t the thickness.
    "L": ("L_shapes.csv", {"d": "d", "bf": "b", "tw": "t", "tf": "t"}),
    "PIPE": ("PIPE_shapes.csv", {"od": "OD", "tnom": "tnom"}),
    "HSS_R": ("HSS_R_shapes.csv", {"od": "OD", "tnom": "tnom"}),
    # Rectangular and square HSS: Ht is the depth, B the width.
    "HSS": ("HSS_shapes.csv", {"d": "Ht", "bf": "B", "tnom": "tnom"}),
}
# DBL_L_shapes.csv is deliberately absent: a double angle is a built-up section
# with its own axis conventions, and the application has no model for it yet.

#: Columns of the output, in order.
COLUMNS = [
    "family",
    "name",
    "weight",
    "area",
    "d",
    "bf",
    "tw",
    "tf",
    "od",
    "tnom",
    "ix",
    "zx",
    "sx",
    "rx",
    "iy",
    "zy",
    "sy",
    "ry",
    "j",
    "cw",
]

#: Property columns read straight from the source, lower-cased on output.
PROPERTIES = ("Ix", "Zx", "Sx", "rx", "Iy", "Zy", "Sy", "ry", "J", "Cw")

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "src/opensees_studio/data/aisc_v16.csv"


def _number(row: dict[str, str], column: str) -> str:
    """The value of ``column`` as written, or empty when absent or unreadable."""
    raw = (row.get(column) or "").strip()
    if not raw:
        return ""
    try:
        return repr(float(raw))
    except ValueError:
        return ""


def build(source: Path, out: Path) -> int:
    """Read the family files under ``source`` and write the normalised table."""
    rows: list[dict[str, str]] = []
    for family, (filename, geometry) in FAMILIES.items():
        path = source / filename
        if not path.is_file():
            raise SystemExit(f"missing {path}; point --source at steelpy's 'shape files'")
        with path.open(newline="", encoding="utf-8") as handle:
            for raw in csv.DictReader(handle):
                name = (raw.get("shape") or "").strip()
                if not name:
                    continue
                row = {
                    "family": family,
                    "name": name,
                    "weight": _number(raw, "weight"),
                    "area": _number(raw, "area"),
                    **{field: _number(raw, column) for field, column in geometry.items()},
                    **{prop.lower(): _number(raw, prop) for prop in PROPERTIES},
                }
                # A shape without an area or Ix cannot drive an elastic section.
                if not row["area"] or not row["ix"]:
                    continue
                rows.append({column: row.get(column, "") for column in COLUMNS})

    rows.sort(key=lambda r: (r["family"], r["name"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    # LF everywhere: the committed table has to be identical on every platform,
    # or a Windows regeneration would show up as a whole-file diff.
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="steelpy's 'shape files'")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    count = build(args.source, args.out)
    print(f"[aisc] wrote {count} shapes to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
