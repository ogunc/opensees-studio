"""The report in Spanish: text runs translated, tags, styles and user data left alone."""

from __future__ import annotations

from opensees_studio.services.report_i18n import SPANISH, translate, translate_html


def test_phrases_and_patterns() -> None:
    assert translate("Load patterns", "es") == "Patrones de carga"
    assert translate("Results — DEAD", "es") == "Resultados — DEAD"
    assert translate("Elevation [m]", "es") == "Elevación [m]"
    assert translate("Final-step reactions (supports)", "es") == (
        "Reacciones del último paso (apoyos)"
    )
    assert translate("3D, 6 DOF per joint (Z up)", "es") == "3D, 6 GDL por nodo (Z arriba)"
    assert translate("2 joint, 4 member", "es") == "2 nodal(es), 4 en barras"
    assert translate("1.4 × case 'DEAD'", "es") == "1.4 × caso 'DEAD'"
    assert translate(
        "10 member(s) checked, 0 over the limit, 0 not designed; largest ratio 0.971 (element 9).",
        "es",
    ) == (
        "10 barra(s) verificada(s), 0 sobre el límite, 0 sin diseñar; "
        "mayor relación 0.971 (elemento 9)."
    )
    assert translate("Storey drift — limit 0.02, amplification 1", "es") == (
        "Deriva de piso — límite 0.02, amplificación 1"
    )


def test_unknown_text_and_english_are_unchanged() -> None:
    assert translate("W16X31", "es") == "W16X31"
    assert translate("Load patterns", "en") == "Load patterns"
    assert translate("  Materials ", "es") == "  Materiales "


def test_html_text_runs_only() -> None:
    page = (
        "<style>td.Model { color: red }</style>"
        '<h2 class="Model"><a name="s1">Model</a></h2>'
        '<img alt="Model" src="data:x"><td>Sum</td><td>a &amp; b</td>'
    )
    out = translate_html(page, "es")
    assert "<style>td.Model { color: red }</style>" in out
    assert '<h2 class="Model"><a name="s1">Modelo</a></h2>' in out
    assert 'alt="Model"' in out and "<td>Suma</td>" in out and "<td>a &amp; b</td>" in out
    assert translate_html(page, "en") == page


def test_layout_words_are_in_the_table() -> None:
    for key in ("Contents", "Calculation report", "Page {page} of {pages}"):
        assert key in SPANISH
