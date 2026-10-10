"""Regenerate ``data/typical_materials.csv`` from the published values it cites.

Nobody types the derived numbers by hand: this script holds the *published*
inputs (a strength in psi or ksi, a density in lb/ft³, a masonry modulus
factor) and computes everything else with the code equation or the exact
conversion factor that the entry's ``standard`` column names. Running it with
``--check`` compares the file on disk with a fresh generation, which is what
``tests/unit/test_material_catalog.py`` does — so a hand-edited CSV fails.

    python tools/build_typical_materials.py            # write the csv
    python tools/build_typical_materials.py --check    # fail if it differs

Sources, all of them documents in the engineering library:

- **ACI 318-25** — ``Ec`` for normalweight concrete, Eq. (19.2.2.1b);
  ``Ec = wc^1.5 · 0.043 √f'c`` for any density, Eq. (19.2.2.1a); ultimate
  compression strain 0.003 (§22.2.2.1); ``Es`` = 200 000 MPa (§20.2.2.2);
  permitted reinforcement grades (§20.2.2.4) and A706 Grades 420/550/690
  (§18.2.6.1); minimum structural ``f'c`` of 17 MPa (§19.2.1.1).
- **AISC 360-22, Chapter A** — ``Fy``/``Fu`` for A992, A36, A572 Gr. 50 and
  A500, and ``E`` = 29 000 ksi.
- **ASCE 41-23** — §11.2.3.4 sends the masonry modulus to TMS 402; Table 4-3
  lists the historic reinforcing-bar grades.
- **ASCE 7-16, Table C3.1-2** — unit weights (densities) of concrete, masonry
  and steel as published in lb/ft³.
- **TMS 402/602 (MSJC)** — ``Em`` = 700 f'm for clay masonry and 900 f'm for
  concrete masonry.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "opensees_studio" / "data" / "typical_materials.csv"

# ── exact conversion factors (the definitions, not rounded tables) ──
LB = 0.45359237  # kg, exact
FT3 = 0.028316846592  # m³, exact
IN2 = 0.00064516  # m², exact
LB_PER_FT3_TO_KG_PER_M3 = LB / FT3  # 16.01846337396014
PSI_TO_MPA = LB * 9.80665 / IN2 / 1e6  # 0.006894757293168361
KSI_TO_MPA = 1000.0 * PSI_TO_MPA  # 6.894757293168361

#: Column order of the generated table.
COLUMNS = [
    "key",
    "family",
    "name",
    "standard",
    "model",
    "fpc_MPa",
    "fpc_psi",
    "epsc0",
    "fpcu_MPa",
    "epsU",
    "Ec_MPa",
    "Fy_MPa",
    "Fy_ksi",
    "Fu_MPa",
    "Fu_ksi",
    "E_MPa",
    "E_ksi",
    "nu",
    "b",
    "R0",
    "cR1",
    "cR2",
    "fm_MPa",
    "fm_psi",
    "Em_MPa",
    "Em_factor",
    "rho_kg_m3",
    "rho_pcf",
    "notes",
]

ACI = "ACI 318-25"
AISC = "AISC 360-22 §A"
ASCE7 = "ASCE 7-16 Table C3.1-2"
TMS = "TMS 402 (E_m = 700 f'm clay / 900 f'm concrete)"
ASCE41 = "ASCE 41-23 Table 4-3"


def _fmt(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}g}"


def concrete(
    psi: float,
    *,
    density_pcf: float,
    note: str,
    lightweight: bool = False,
) -> dict[str, object]:
    """One unconfined Kent-Scott-Park concrete, from its specified strength.

    ``Concrete01`` takes the peak strength, the strain at peak, the crushing
    strength and the crushing strain; 0.002 and 0.003 are the conventional
    peak and ultimate strains (the latter is ACI's 0.003), and the crushing
    strength is 20 % of the peak.
    """
    fpc = psi * PSI_TO_MPA
    rho = density_pcf * LB_PER_FT3_TO_KG_PER_M3
    # ACI 318-25 Eq. (19.2.2.1b) for normalweight; Eq. (19.2.2.1a) otherwise.
    ec = 4700.0 * fpc**0.5 if not lightweight else rho**1.5 * 0.043 * fpc**0.5
    label = "lightweight" if lightweight else "normal weight"
    return {
        "key": f"concrete_{int(psi)}" + ("_lightweight" if lightweight else "") + "_unconfined",
        "family": "concrete",
        "name": f"Concrete f'c = {psi:.0f} psi ({fpc:.1f} MPa), {label}, unconfined",
        "standard": f"{ACI} §19.2.2.1, §22.2.2.1",
        "model": "Concrete01",
        "fpc_MPa": fpc,
        "fpc_psi": psi,
        "epsc0": -0.002,
        # The table carries strengths as positive magnitudes; the model's own
        # sign convention (compression negative) is applied when it is built.
        "fpcu_MPa": 0.2 * fpc,
        "epsU": -0.003,
        "Ec_MPa": ec,
        "rho_kg_m3": rho,
        "rho_pcf": density_pcf,
        "notes": note,
    }


def rebar(
    *, key: str, name: str, fy: float, standard: str, note: str, b: float = 0.01
) -> dict[str, object]:
    """Reinforcing steel as ``Steel02`` (Giuffre-Menegotto-Pinto)."""
    return {
        "key": key,
        "family": "rebar",
        "name": name,
        "standard": standard,
        "model": "Steel02",
        "Fy_MPa": fy,
        "E_MPa": 199947.95,  # 29 000 ksi, exactly
        "E_ksi": 29000.0,
        "b": b,
        "R0": 18.0,
        "cR1": 0.925,
        "cR2": 0.15,
        "rho_kg_m3": 492.0 * LB_PER_FT3_TO_KG_PER_M3,
        "rho_pcf": 492.0,
        "notes": note,
    }


def structural_steel(
    *, key: str, name: str, fy_ksi: float, fu_ksi: float, note: str, b: float = 0.02
) -> dict[str, object]:
    """Structural steel as ``Steel02``, from the AISC tabulated ksi values."""
    return {
        "key": key,
        "family": "structural_steel",
        "name": name,
        "standard": AISC,
        "model": "Steel02",
        "Fy_MPa": fy_ksi * KSI_TO_MPA,
        "Fy_ksi": fy_ksi,
        "Fu_MPa": fu_ksi * KSI_TO_MPA,
        "Fu_ksi": fu_ksi,
        "E_MPa": 29000.0 * KSI_TO_MPA,
        "E_ksi": 29000.0,
        "b": b,
        "R0": 18.0,
        "cR1": 0.925,
        "cR2": 0.15,
        "rho_kg_m3": 492.0 * LB_PER_FT3_TO_KG_PER_M3,
        "rho_pcf": 492.0,
        "notes": note,
    }


def masonry(
    *, key: str, name: str, fm_psi: float, factor: float, density_pcf: float, note: str
) -> dict[str, object]:
    """Masonry as an elastic isotropic material (walls are modelled with shells)."""
    fm = fm_psi * PSI_TO_MPA
    return {
        "key": key,
        "family": "masonry",
        "name": name,
        "standard": f"{TMS}; {ASCE41}",
        "model": "ElasticIsotropic",
        "E_MPa": factor * fm,
        "fm_MPa": fm,
        "fm_psi": fm_psi,
        "Em_MPa": factor * fm,
        "Em_factor": factor,
        "nu": 0.2,
        "rho_kg_m3": density_pcf * LB_PER_FT3_TO_KG_PER_M3,
        "rho_pcf": density_pcf,
        "notes": note,
    }


def elastic_steel() -> dict[str, object]:
    """Plain elastic steel, for a model that will stay in the elastic range."""
    return {
        "key": "steel_elastic",
        "family": "structural_steel",
        "name": "Structural steel, elastic (E only)",
        "standard": AISC,
        "model": "ElasticUniaxial",
        "E_MPa": 29000.0 * KSI_TO_MPA,
        "E_ksi": 29000.0,
        "rho_kg_m3": 492.0 * LB_PER_FT3_TO_KG_PER_M3,
        "rho_pcf": 492.0,
        "notes": "No yield: for a linear analysis, where the section's E is what "
        "matters. AISC tabulates E = 29 000 ksi; 200 000 MPa is the usual rounded value.",
    }


def rows() -> list[dict[str, object]]:
    """The whole library, in the order the picker shows it."""
    #: ASCE 7-16 Table C3.1-2: reinforced concrete of stone aggregate, 150 lb/ft³.
    concrete_note = (
        "f'c is the specified strength; 0.002 and 0.003 are the conventional peak "
        "and crushing strains (ACI 318-25 uses 0.003 at the extreme compression "
        "fibre) and the crushing strength is 20 % of the peak. Concrete01 carries "
        "no modulus: Ec is shown for information, from ACI 318-25 Eq. (19.2.2.1)."
    )
    out: list[dict[str, object]] = [
        concrete(2500, density_pcf=150.0, note=concrete_note),
        concrete(3000, density_pcf=150.0, note=concrete_note),
        concrete(3500, density_pcf=150.0, note=concrete_note),
        concrete(4000, density_pcf=150.0, note=concrete_note),
        concrete(5000, density_pcf=150.0, note=concrete_note),
        concrete(6000, density_pcf=150.0, note=concrete_note),
        concrete(
            4000,
            density_pcf=110.0,
            lightweight=True,
            note=concrete_note + " Lightweight: Ec from Eq. (19.2.2.1a) with wc = 110 lb/ft³.",
        ),
        rebar(
            key="rebar_grade_280",
            name="Reinforcing steel, Grade 280 (40 ksi)",
            fy=280.0,
            standard=f"{ACI} §20.2.2.4; {ASCE41}",
            note="Historic Grade 40: 40 ksi = 275.8 MPa, which ACI designates Grade 280. "
            "Hardening b = 0.01 is a modelling choice; R0/cR1/cR2 are the OpenSees defaults.",
        ),
        rebar(
            key="rebar_grade_420",
            name="Reinforcing steel, Grade 420 (60 ksi)",
            fy=420.0,
            standard=f"{ACI} §20.2.2.4",
            note="The everyday Grade 60 bar, in ACI's SI designation. "
            "Hardening b = 0.01 is a modelling choice; R0/cR1/cR2 are the OpenSees defaults.",
        ),
        rebar(
            key="rebar_grade_550",
            name="Reinforcing steel, Grade 550 (80 ksi)",
            fy=550.0,
            standard=f"{ACI} §20.2.2.4",
            note="Grade 80: 80 ksi = 551.6 MPa, which ACI designates Grade 550. "
            "Hardening b = 0.01 is a modelling choice.",
        ),
        rebar(
            key="rebar_a706_420",
            name="Reinforcing steel, ASTM A706 Grade 420",
            fy=420.0,
            standard=f"{ACI} §18.2.6.1, §20.2.2.4",
            note="Weldable low-alloy bar for seismic detailing. A706 also specifies a "
            "tensile strength, which this library does not carry: it is not an input to "
            "Steel02. Hardening b = 0.01 is a modelling choice.",
        ),
        rebar(
            key="rebar_a706_550",
            name="Reinforcing steel, ASTM A706 Grade 550",
            fy=550.0,
            standard=f"{ACI} §18.2.6.1",
            note="Permitted in special structural walls (ACI 318-25 §18.2.6.1). "
            "Hardening b = 0.01 is a modelling choice.",
        ),
        rebar(
            key="rebar_a706_690",
            name="Reinforcing steel, ASTM A706 Grade 690",
            fy=690.0,
            standard=f"{ACI} §18.2.6.1",
            note="High-strength weldable bar for walls; ACI 318-25 §18.2.6.1 allows it "
            "only where its use is justified by test data.",
        ),
        structural_steel(
            key="steel_a992",
            name="Structural steel, ASTM A992 (50 ksi)",
            fy_ksi=50.0,
            fu_ksi=65.0,
            note="The usual W-shape steel: Fy = 50 ksi, Fu = 65 ksi. "
            "Hardening b = 0.02 is a modelling choice for a frame analysis.",
        ),
        structural_steel(
            key="steel_a36",
            name="Structural steel, ASTM A36 (36 ksi)",
            fy_ksi=36.0,
            fu_ksi=58.0,
            note="Plates, angles and channels: Fy = 36 ksi, Fu = 58 ksi (the lower "
            "bound of the 58-80 ksi range A36 permits).",
        ),
        structural_steel(
            key="steel_a572_50",
            name="Structural steel, ASTM A572 Gr. 50 (50 ksi)",
            fy_ksi=50.0,
            fu_ksi=65.0,
            note="High-strength low-alloy plate and shape steel: Fy = 50 ksi, Fu = 65 ksi.",
        ),
        structural_steel(
            key="steel_a500_b",
            name="Structural steel, ASTM A500 Gr. B (46 ksi)",
            fy_ksi=46.0,
            fu_ksi=58.0,
            note="Cold-formed round and rectangular HSS: Gr. B is Fy = 46 ksi "
            "(42 ksi for round sections), Fu = 58 ksi. Gr. C is 50/62.",
        ),
        elastic_steel(),
        masonry(
            key="masonry_clay_1500",
            name="Clay masonry, f'm = 1500 psi (10.3 MPa)",
            fm_psi=1500.0,
            factor=700.0,
            density_pcf=130.0,
            note="Solid clay brick, hard (low absorption). Em = 700 f'm per TMS 402, "
            "which ASCE 41-23 §11.2.3.4 names as the source of the masonry modulus. "
            "Poisson's ratio 0.2 is typical; masonry is really orthotropic.",
        ),
        masonry(
            key="masonry_clay_2000",
            name="Clay masonry, f'm = 2000 psi (13.8 MPa)",
            fm_psi=2000.0,
            factor=700.0,
            density_pcf=130.0,
            note="Same brick at the higher specified strength: Em = 700 f'm.",
        ),
        masonry(
            key="masonry_cmu_normal_1500",
            name="Concrete block masonry, normal weight, f'm = 1500 psi (10.3 MPa)",
            fm_psi=1500.0,
            factor=900.0,
            density_pcf=135.0,
            note="Ungrouted hollow concrete units, normal weight. Em = 900 f'm per TMS 402.",
        ),
        masonry(
            key="masonry_cmu_grouted_2000",
            name="Concrete block masonry, grouted, f'm = 2000 psi (13.8 MPa)",
            fm_psi=2000.0,
            factor=900.0,
            density_pcf=140.0,
            note="Fully grouted cells; 140 lb/ft³ is the tabulated weight of masonry grout. "
            "Em = 900 f'm.",
        ),
        masonry(
            key="masonry_cmu_lightweight_1500",
            name="Concrete block masonry, lightweight, f'm = 1500 psi (10.3 MPa)",
            fm_psi=1500.0,
            factor=900.0,
            density_pcf=105.0,
            note="Lightweight units: the same modulus rule and a much lighter wall, "
            "which is what a dynamic analysis feels.",
        ),
    ]
    return out


def render() -> str:
    """The CSV text, one header row and one row per material."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows():
        line = {}
        for column in COLUMNS:
            value = row.get(column, "")
            line[column] = _fmt(value) if isinstance(value, float) else value
        writer.writerow(line)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check = "--check" in args
    text = render()
    if check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET} is not what this script generates", file=sys.stderr)
            return 1
        print(f"{TARGET.name}: up to date ({len(rows())} materials)")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET} ({len(rows())} materials, {len(COLUMNS)} columns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
