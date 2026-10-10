"""The help content itself: complete, linked, and readable.

The window is tested in ``tests/gui/test_help_window.py``; what is pinned here is
that no menu action is left without a page, that no page is orphaned, that every
cross-reference points at something, and that the tiny markup renders.
"""

from __future__ import annotations

import pytest

from opensees_studio.core.help import (
    ACTION_TOPICS,
    DEFAULT_TOPIC,
    GROUP_ORDER,
    TOPICS,
    body_to_html,
    groups_present,
    resolve_topic,
    topic,
    topics_in_group,
)


# ──────────────────────────── completeness ────────────────────────────
def test_every_action_has_a_page() -> None:
    missing = sorted({topic_id for topic_id in ACTION_TOPICS.values() if topic_id not in TOPICS})
    assert missing == [], f"acciones sin ayuda: {missing}"


def test_the_default_page_exists() -> None:
    assert DEFAULT_TOPIC in TOPICS
    assert topic("no-such-topic") is TOPICS[DEFAULT_TOPIC]


def test_every_page_is_reachable() -> None:
    """A page nobody links to (and no action opens) is a page nobody reads."""
    reachable = set(ACTION_TOPICS.values()) | {DEFAULT_TOPIC}
    for entry in TOPICS.values():
        reachable.update(entry.see_also)
    orphans = sorted(set(TOPICS) - reachable)
    assert orphans == [], f"páginas sin enlace: {orphans}"


def test_every_cross_reference_points_somewhere() -> None:
    broken = sorted(
        {target for entry in TOPICS.values() for target in entry.see_also if target not in TOPICS}
    )
    assert broken == [], f"referencias rotas: {broken}"


def test_every_page_has_a_title_a_summary_and_a_body() -> None:
    thin = sorted(
        topic_id
        for topic_id, entry in TOPICS.items()
        if not entry.title
        or not entry.summary
        or len(entry.body.strip()) < 80  # a page with a title and nothing else
    )
    assert thin == [], f"páginas vacías: {thin}"


def test_every_page_sits_in_a_known_group() -> None:
    unknown = sorted({entry.group for entry in TOPICS.values()} - set(GROUP_ORDER))
    assert unknown == [], f"grupos desconocidos: {unknown}"
    assert groups_present() == [g for g in GROUP_ORDER if g in {e.group for e in TOPICS.values()}]


def test_a_group_lists_its_own_pages() -> None:
    for group in groups_present():
        listed = topics_in_group(group)
        assert listed, f"{group} no tiene páginas"
        assert all(entry.group == group for _, entry in listed)


# ──────────────────────────── the markup ────────────────────────────
def test_paragraphs_bullets_and_bold_render() -> None:
    html = body_to_html("One line.\n\n- first\n- second\n\n**bold** text")

    assert "<p>One line.</p>" in html
    assert "<ul><li>first</li><li>second</li></ul>" in html
    assert "<b>bold</b> text" in html


def test_a_hash_line_is_a_heading() -> None:
    assert body_to_html("# Parameters\n\nText.").startswith("<h3>Parameters</h3>")


def test_bullets_are_closed_by_a_paragraph() -> None:
    html = body_to_html("- a\n- b\n\nAfter.")

    assert html.index("</ul>") < html.index("<p>After.</p>")


def test_markup_in_the_text_is_escaped() -> None:
    """Help text is not HTML: a `<` in a formula must not become a tag."""
    html = body_to_html("a < b and c > d")

    assert "&lt;" in html and "&gt;" in html


def test_the_page_html_links_its_cross_references() -> None:
    entry = TOPICS["index"]

    html = entry.html()

    assert f"<h2>{entry.title}</h2>" in html
    assert '<a href="topic:concepts.units">' in html
    assert "See also" in html


@pytest.mark.parametrize("topic_id", sorted(TOPICS))
def test_every_page_renders_without_raising(topic_id: str) -> None:
    html = TOPICS[topic_id].html()

    assert html.startswith("<h2>")
    assert len(html) > 100


# ──────────────────────────── which page F1 shows ────────────────────────────
def test_the_highlighted_item_wins() -> None:
    assert (
        resolve_topic(
            highlighted="edit.replicate",
            menu_first="edit.undo",
            widget_topics=("file.new",),
        )
        == "edit.replicate"
    )


def test_an_open_menu_with_no_highlight_shows_its_first_entry() -> None:
    assert resolve_topic(menu_first="edit.undo", widget_topics=("file.new",)) == "edit.undo"


def test_a_dialog_on_top_is_read_when_no_menu_is_open() -> None:
    assert resolve_topic(widget_topics=(None, "define.portal_frame")) == "define.portal_frame"


def test_an_unknown_topic_is_ignored_rather_than_shown_blank() -> None:
    assert resolve_topic(highlighted="nope", menu_first="nope", widget_topics=("nope",)) == (
        DEFAULT_TOPIC
    )
    assert resolve_topic() == DEFAULT_TOPIC
