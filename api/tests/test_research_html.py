import pytest

from app.research.html import html_to_text


@pytest.mark.parametrize(
    "html,expected_contains,expected_excludes",
    [
        ("<p>Held: the statute is <em>void</em>.</p>", "Held: the statute is void.", "<p>"),
        ("<div><p>One.</p><p>Two.</p></div>", "One.", "<div>"),
        ("<span class='citation'>347 U.S. 483</span> applies", "347 U.S. 483", "<span"),
        ("plain text already", "plain text already", "<"),
    ],
)
def test_html_to_text(html, expected_contains, expected_excludes) -> None:
    out = html_to_text(html)
    assert expected_contains in out
    assert expected_excludes not in out


def test_html_to_text_collapses_whitespace() -> None:
    out = html_to_text("<p>One.</p>\n\n   <p>Two.</p>")
    assert "One." in out and "Two." in out
    assert "  " not in out  # runs of spaces collapsed


def test_html_to_text_handles_entities() -> None:
    assert "Smith & Jones" in html_to_text("<p>Smith &amp; Jones</p>")


def test_html_to_text_drops_script_style_content() -> None:
    out = html_to_text("<p>Visible.</p><script>var x=1;</script><style>.a{}</style>")
    assert "Visible." in out
    assert "var x" not in out
    assert ".a{}" not in out
