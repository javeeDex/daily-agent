from renderer import markdown_to_html, render_email, render_list


def content(**overrides):
    data = {
        "today": [{"category": "Consultoría", "tasks": ["Tarea 1"]}],
        "priorities": ["Prioridad 1"],
        "risks": [{"risk": "Riesgo", "mitigation": "Plan"}],
        "blockers": ["Bloqueo"],
        "commitments": "Compromiso",
        "growth": "Crecimiento",
    }
    data.update(overrides)
    return data


def test_markdown_to_html_plain_text_is_escaped():
    assert markdown_to_html("a < b & c") == "a &lt; b &amp; c"


def test_markdown_to_html_converts_links():
    html = markdown_to_html("Ver [Tarea](https://app.asana.com/1) ahora")
    assert html == 'Ver <a href="https://app.asana.com/1">Tarea</a> ahora'


def test_markdown_to_html_multiple_links_and_escaping():
    html = markdown_to_html('[<a>](https://x.com/?a=1&b="2") y [b](http://y.com)')
    assert html == (
        '<a href="https://x.com/?a=1&amp;b=&quot;2&quot;">&lt;a&gt;</a>'
        ' y <a href="http://y.com">b</a>'
    )


def test_markdown_to_html_ignores_non_http_links():
    assert markdown_to_html("[x](javascript:alert(1))") == "[x](javascript:alert(1))"


def test_render_list_empty():
    assert render_list([]) == "<ul><li>-</li></ul>"


def test_render_list_items():
    assert render_list(["a", "<b>"]) == "<ul><li>a</li><li>&lt;b&gt;</li></ul>"


def test_render_email_contains_all_sections():
    html = render_email(content())
    assert html.startswith("<!doctype html>")
    for text in ["Qué haré hoy", "<strong>Consultoría</strong>", "<li>Tarea 1</li>",
                 "Top 5 prioridades", "<li>Prioridad 1</li>",
                 "<li>Riesgo. Mitigación: Plan</li>", "<li>Bloqueo</li>",
                 "Compromisos del día:</strong> Compromiso",
                 "Rol/Líder:</strong> Crecimiento"]:
        assert text in html


def test_render_email_risk_without_mitigation():
    html = render_email(content(risks=[{"risk": "Solo riesgo", "mitigation": ""}]))
    assert "<li>Solo riesgo</li>" in html
    assert "Mitigación" not in html


def test_render_email_defaults_for_empty_values():
    html = render_email(content(risks=[], blockers=[], priorities=[], commitments="", growth=""))
    assert "<li>Ninguno identificado por el momento!</li>" in html
    assert "Compromisos del día:</strong> -</p>" in html
    assert "Rol/Líder:</strong> -</p>" in html


def test_render_email_escapes_category():
    html = render_email(content(today=[{"category": "A & B", "tasks": []}]))
    assert "<strong>A &amp; B</strong><ul><li>-</li></ul>" in html
