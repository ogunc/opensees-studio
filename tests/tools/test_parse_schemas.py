"""
Tests for tools/gidopensees_import/parse_schemas.py.

Fast tests run without gidopensees present (snapshot + unit tests).
Integration tests that read the real .mat/.cnd files are skipped when the
files cannot be found, so CI still passes in environments without the
upstream repo checked out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.gidopensees_import.parse_schemas import (
    ParseError,
    _parse_dependencies,
    _parse_question,
    _parse_value,
    build_catalog,
    parse_mat,
)
from tools.gidopensees_import.schema_model import CatalogSpec

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
MINIMAL_MAT = FIXTURES / "minimal.mat"
MINIMAL_EXPECTED = FIXTURES / "minimal_expected.json"

GIDOPENSEES = Path("d:/GitHub/gidopensees")
REAL_MAT = GIDOPENSEES / "OpenSees.mat"
REAL_CND = GIDOPENSEES / "OpenSees.cnd"

_have_real = REAL_MAT.exists() and REAL_CND.exists()
real_files = pytest.mark.skipif(not _have_real, reason="gidopensees repo not present")


# ---------------------------------------------------------------------------
# Unit tests — _parse_question
# ---------------------------------------------------------------------------


class TestParseQuestion:
    def test_cb_with_options(self) -> None:
        name, wtype, opts = _parse_question("Formulation#CB#(Stress-Strain,Force-Deformation)")
        assert name == "Formulation"
        assert wtype == "CB"
        assert opts == ["Stress-Strain", "Force-Deformation"]

    def test_cb_single_underscore(self) -> None:
        name, wtype, opts = _parse_question("_#CB#(_)")
        assert name == "_"
        assert wtype == "CB"
        assert opts == ["_"]

    def test_units(self) -> None:
        name, wtype, opts = _parse_question("Elastic_modulus_E#UNITS#")
        assert name == "Elastic_modulus_E"
        assert wtype == "UNITS"
        assert opts == []

    def test_mat_with_books(self) -> None:
        name, wtype, opts = _parse_question(
            "Ux_material#MAT#(Standard_Uniaxial_Materials,Uniaxial_Steel_Materials)"
        )
        assert name == "Ux_material"
        assert wtype == "MAT"
        assert "Standard_Uniaxial_Materials" in opts

    def test_tuple(self) -> None:
        name, wtype, opts = _parse_question(
            "Cyclic_data(Max_compressive_strain,Max_tensile_strain,Number_of_cycles)"
        )
        assert name == "Cyclic_data"
        assert wtype == "TUPLE"
        assert opts == ["Max_compressive_strain", "Max_tensile_strain", "Number_of_cycles"]

    def test_plain_scalar(self) -> None:
        name, wtype, opts = _parse_question("Parameter_R0")
        assert name == "Parameter_R0"
        assert wtype == "SCALAR"
        assert opts == []

    def test_label_with_trailing_colon(self) -> None:
        name, wtype, opts = _parse_question("Material:#CB#(Steel02)")
        assert name == "Material"
        assert wtype == "CB"
        assert opts == ["Steel02"]

    def test_plain_label_colon(self) -> None:
        name, wtype, _opts = _parse_question("Layer_name:")
        assert name == "Layer_name"
        assert wtype == "SCALAR"

    def test_cb_no_options(self) -> None:
        name, wtype, opts = _parse_question("Section:#CB#(Fiber)")
        assert name == "Section"
        assert wtype == "CB"
        assert opts == ["Fiber"]


# ---------------------------------------------------------------------------
# Unit tests — _parse_value
# ---------------------------------------------------------------------------


class TestParseValue:
    def test_simple(self) -> None:
        val, width = _parse_value("30 GPa")
        assert val == "30 GPa"
        assert width is None

    def test_width_suffix(self) -> None:
        val, width = _parse_value("0.0#WIDTH#(10)")
        assert val == "0.0"
        assert width == 10

    def test_number_width(self) -> None:
        val, width = _parse_value("20#WIDTH#(10)")
        assert val == "20"
        assert width == 10

    def test_n_prefix(self) -> None:
        val, width = _parse_value("#N# 3 -0.005 0.005 5")
        assert val == "#N# 3 -0.005 0.005 5"
        assert width is None

    def test_empty(self) -> None:
        val, width = _parse_value("")
        assert val == ""
        assert width is None


# ---------------------------------------------------------------------------
# Unit tests — _parse_dependencies
# ---------------------------------------------------------------------------


class TestParseDependencies:
    _path = Path("test.mat")

    def test_single_group_restore_hide(self) -> None:
        s = "(Stress-Strain,RESTORE,Mat_type,#CURRENT#,HIDE,Stiffness_K,#CURRENT#)"
        rules = _parse_dependencies(s, self._path, 1)
        assert len(rules) == 1
        rule = rules[0]
        assert rule.trigger == "Stress-Strain"
        assert len(rule.actions) == 2
        assert rule.actions[0].action == "RESTORE"
        assert rule.actions[0].field == "Mat_type"
        assert rule.actions[1].action == "HIDE"
        assert rule.actions[1].field == "Stiffness_K"

    def test_two_groups_same_line(self) -> None:
        s = "(0,SET,Rz_material,#CURRENT#) (1,RESTORE,Rz_material,#CURRENT#)"
        rules = _parse_dependencies(s, self._path, 1)
        assert len(rules) == 2
        assert rules[0].trigger == "0"
        assert rules[0].actions[0].action == "SET"
        assert rules[1].trigger == "1"
        assert rules[1].actions[0].action == "RESTORE"

    def test_set_with_literal_value(self) -> None:
        s = "(1,SET,Void_width_dv,0.0m,SET,Number_of_voids,0)"
        rules = _parse_dependencies(s, self._path, 1)
        assert len(rules) == 1
        assert rules[0].actions[0].target == "0.0m"
        assert rules[0].actions[1].target == "0"

    def test_no_groups_raises(self) -> None:
        with pytest.raises(ParseError):
            _parse_dependencies("no parentheses here", self._path, 5)

    def test_literal_integer_trigger(self) -> None:
        s = "(1,RESTORE,Gap_length,#CURRENT#)"
        rules = _parse_dependencies(s, self._path, 1)
        assert rules[0].trigger == "1"

    def test_fix_xyz_multi_action(self) -> None:
        s = "(Fix_XYZ,RESTORE,X-Translation,1,RESTORE,Y-Translation,1,RESTORE,Z-Translation,1)"
        rules = _parse_dependencies(s, self._path, 1)
        assert len(rules) == 1
        assert rules[0].trigger == "Fix_XYZ"
        assert len(rules[0].actions) == 3
        for act in rules[0].actions:
            assert act.target == "1"


# ---------------------------------------------------------------------------
# Snapshot test — minimal fixture
# ---------------------------------------------------------------------------


class TestSnapshotMinimal:
    def test_minimal_mat_matches_golden(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        cat = CatalogSpec(mat_books=books)
        actual = json.loads(cat.model_dump_json())
        expected = json.loads(MINIMAL_EXPECTED.read_text(encoding="utf-8"))
        assert actual == expected

    def test_minimal_has_one_book(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        assert len(books) == 1
        assert books[0].name == "Test_Book"

    def test_minimal_entry_fields(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        entry = books[0].entries[0]
        assert entry.name == "TestMaterial"
        assert entry.comment.startswith("A minimal test material")
        field_names = [f.name for f in entry.fields]
        assert "Elastic_modulus_E" in field_names
        assert "Stiffness_K" in field_names
        assert "Gap_size" in field_names
        assert "Combo_sub" in field_names

    def test_formulation_two_deps(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        entry = books[0].entries[0]
        form = next(f for f in entry.fields if f.name == "Formulation")
        assert len(form.dependencies) == 2
        triggers = {d.trigger for d in form.dependencies}
        assert "Stress-Strain" in triggers
        assert "Force-Deformation" in triggers

    def test_gap_size_width_hint(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        entry = books[0].entries[0]
        gap = next(f for f in entry.fields if f.name == "Gap_size")
        assert gap.default == "0.0"
        assert gap.width_hint == 10

    def test_hidden_button_field(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        entry = books[0].entries[0]
        hidden = [f for f in entry.fields if f.state == "HIDDEN"]
        assert any(f.name == "_" and "TK_MaterialTester" in f.tkwidgets for f in hidden)

    def test_tkwidget_on_first_field(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        entry = books[0].entries[0]
        mat_field = entry.fields[0]
        assert mat_field.name == "Material"
        assert "TK_UpdateInfoBar" in mat_field.tkwidgets
        assert mat_field.image == "img/test.png"

    def test_tuple_field(self) -> None:
        books = parse_mat(MINIMAL_MAT)
        entry = books[0].entries[0]
        combo = next(f for f in entry.fields if f.name == "Combo_sub")
        assert combo.widget_type == "TUPLE"
        assert combo.options == ["Val_A", "Val_B", "Val_C"]
        assert combo.default == "#N# 3 1.0 2.0 3.0"


# ---------------------------------------------------------------------------
# Integration tests — real gidopensees files
# ---------------------------------------------------------------------------


@real_files
class TestRealFiles:
    def test_mat_book_count(self, catalog: CatalogSpec) -> None:
        assert len(catalog.mat_books) == 14

    def test_cnd_book_count(self, catalog: CatalogSpec) -> None:
        assert len(catalog.cnd_books) == 6

    def test_mat_material_count(self, catalog: CatalogSpec) -> None:
        total = sum(len(b.entries) for b in catalog.mat_books)
        assert total == 58

    def test_cnd_condition_count(self, catalog: CatalogSpec) -> None:
        total = sum(len(b.entries) for b in catalog.cnd_books)
        assert total >= 39

    def test_steel02_field_names(self, catalog: CatalogSpec) -> None:
        steel2 = _find_entry(catalog, "Steel02")
        assert steel2 is not None
        fnames = {f.name for f in steel2.fields}
        required = {
            "Steel_grade",
            "Yield_Stress_Fy",
            "Strain-hardening_ratio_b",
            "Parameter_R0",
            "Parameter_cR1",
            "Parameter_cR2",
        }
        assert required.issubset(fnames), f"Missing: {required - fnames}"

    def test_steel02_formulation_three_deps(self, catalog: CatalogSpec) -> None:
        steel2 = _find_entry(catalog, "Steel02")
        assert steel2 is not None
        form = next(f for f in steel2.fields if f.name == "Formulation")
        assert len(form.dependencies) == 3, (
            f"Expected 3 dependency rules on Formulation, got {len(form.dependencies)}"
        )

    def test_steel02_formulation_dep_triggers(self, catalog: CatalogSpec) -> None:
        steel2 = _find_entry(catalog, "Steel02")
        assert steel2 is not None
        form = next(f for f in steel2.fields if f.name == "Formulation")
        triggers = {d.trigger for d in form.dependencies}
        assert triggers == {"Stress-Strain", "Force-Deformation", "Moment-Rotation"}

    def test_concrete04_exists(self, catalog: CatalogSpec) -> None:
        entry = _find_entry(catalog, "Concrete04_(Popovics_concrete)")
        assert entry is not None
        assert entry.book == "Uniaxial_Concrete_Materials"

    def test_all_mat_entries_have_book(self, catalog: CatalogSpec) -> None:
        for book in catalog.mat_books:
            for entry in book.entries:
                assert entry.book == book.name, (
                    f"{entry.name!r} has book={entry.book!r}, expected {book.name!r}"
                )

    def test_all_fields_have_valid_widget_type(self, catalog: CatalogSpec) -> None:
        valid = {"CB", "UNITS", "MAT", "SCALAR", "TUPLE"}
        for book in catalog.mat_books:
            for entry in book.entries:
                for f in entry.fields:
                    assert f.widget_type in valid, (
                        f"{entry.name}.{f.name}: unknown widget_type={f.widget_type!r}"
                    )

    def test_point_restraints_condtype(self, catalog: CatalogSpec) -> None:
        entry = _find_cnd_entry(catalog, "Point_Restraints")
        assert entry is not None
        assert "point" in entry.condtype.lower()
        assert "node" in entry.condmeshtype.lower()

    def test_zerolength_mat_fields(self, catalog: CatalogSpec) -> None:
        entry = _find_cnd_entry(catalog, "Point_ZeroLength")
        assert entry is not None
        mat_fields = [f for f in entry.fields if f.widget_type == "MAT"]
        assert len(mat_fields) >= 6  # Ux,Uy,Uz,Rx,Ry,Rz materials

    def test_no_empty_field_names(self, catalog: CatalogSpec) -> None:
        for book in catalog.mat_books + catalog.cnd_books:
            for entry in book.entries:
                for f in entry.fields:
                    assert f.name, f"{entry.name} has a field with empty name"

    def test_dependencies_actions_are_valid(self, catalog: CatalogSpec) -> None:
        valid_actions = {"RESTORE", "HIDE", "SET"}
        for book in catalog.mat_books + catalog.cnd_books:
            for entry in book.entries:
                for fspec in entry.fields:
                    for rule in fspec.dependencies:
                        for act in rule.actions:
                            assert act.action in valid_actions, (
                                f"{entry.name}.{fspec.name}: invalid action {act.action!r}"
                            )


# ---------------------------------------------------------------------------
# Fixtures (pytest)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def catalog() -> CatalogSpec:
    return build_catalog(REAL_MAT, REAL_CND)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_entry(catalog: CatalogSpec, name: str) -> object | None:
    for book in catalog.mat_books:
        for entry in book.entries:
            if entry.name == name:
                return entry
    return None


def _find_cnd_entry(catalog: CatalogSpec, name: str) -> object | None:
    for book in catalog.cnd_books:
        for entry in book.entries:
            if entry.name == name:
                return entry
    return None
