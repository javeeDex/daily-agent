from pathlib import Path

import pytest

from parser import DailyData, _clean_bullet, parse_daily

ROOT = Path(__file__).resolve().parent.parent


def write(tmp_path, text):
    path = tmp_path / "daily.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("line, expected", [
    ("- tarea", "tarea"),
    ("   -   tarea  ", "tarea"),
    ("tarea sin guion", "tarea sin guion"),
    ("-", ""),
    ("- a - b", "a - b"),
])
def test_clean_bullet(line, expected):
    assert _clean_bullet(line) == expected


def test_parse_example_file():
    data = parse_daily(ROOT / "data" / "example.md")
    assert isinstance(data, DailyData)
    assert [g["category"] for g in data.today] == [
        "Consultoría", "Desarrollo de negocio", "Innovation Lab", "IA", "Equipo",
    ]
    assert data.today[1]["tasks"] == [
        "Revisar y mejorar propuesta [Invicta Finance](https://app.asana.com/example2)",
        "War-room [Acciona Impact Lab](https://app.asana.com/example3)",
    ]
    assert data.today[3]["tasks"] == []  # "-" placeholder is dropped
    assert [p["priority"] for p in data.priorities] == [1, 2, 3, 4, 5]
    assert data.priorities[0]["text"] == "Enviar propuesta Acciona Impact Lab"
    assert data.risks == [{
        "risk": "Lentitud en la respuesta de algunas leads",
        "mitigation": "Convocadas reuniones hoy para acelerar",
    }]
    assert data.blockers == []
    assert len(data.commitments) == 2
    assert data.growth == [
        "Entender mejor al equipo y las capacidades para diseñar una buena estrategia de innovación"
    ]


def test_parse_template_is_empty_but_valid():
    data = parse_daily(ROOT / "daily-template.md")
    assert all(group["tasks"] == [] for group in data.today)
    assert "Tareas ASANA" in [g["category"] for g in data.today]
    assert data.priorities == []
    assert data.risks == data.blockers == data.commitments == data.growth == []


def test_to_dict_returns_all_sections(tmp_path):
    data = parse_daily(write(tmp_path, "# TODAY\n## A\n- x\n"))
    assert data.to_dict() == {
        "today": [{"category": "A", "tasks": ["x"]}],
        "priorities": [], "risks": [], "blockers": [], "commitments": [], "growth": [],
    }


def test_section_names_are_case_insensitive(tmp_path):
    data = parse_daily(write(tmp_path, "# today\n## A\n- x\n# Blockers\n- b\n"))
    assert data.today[0]["tasks"] == ["x"]
    assert data.blockers == ["b"]


def test_priorities_are_sorted_and_case_insensitive(tmp_path):
    data = parse_daily(write(tmp_path, "# PRIORITIES\n[P3] c\n[p1] a\n[P2]   b\n"))
    assert data.priorities == [
        {"priority": 1, "text": "a"},
        {"priority": 2, "text": "b"},
        {"priority": 3, "text": "c"},
    ]


def test_priority_placeholder_is_skipped(tmp_path):
    data = parse_daily(write(tmp_path, "# PRIORITIES\n[P1] real\n[P2] -\n"))
    assert data.priorities == [{"priority": 1, "text": "real"}]


def test_risk_without_mitigation_and_lowercase_mitigation(tmp_path):
    data = parse_daily(write(tmp_path, "# RISKS\n- r1\n- r2\nmitigation:  m2\n"))
    assert data.risks == [
        {"risk": "r1", "mitigation": ""},
        {"risk": "r2", "mitigation": "m2"},
    ]


def test_blank_lines_are_ignored(tmp_path):
    data = parse_daily(write(tmp_path, "\n\n# GROWTH\n\n- g\n\n"))
    assert data.growth == ["g"]


@pytest.mark.parametrize("text, message", [
    ("# UNKNOWN\n", "Sección desconocida: UNKNOWN"),
    ("# TODAY\n- tarea\n", "antes de una categoría"),
    ("# PRIORITIES\nsin formato\n", "Prioridad inválida"),
    ("# PRIORITIES\n[P0] cero\n", "Prioridad inválida"),
    ("# RISKS\nMITIGATION: algo\n", "MITIGATION sin riesgo anterior"),
    ("suelto\n", "Contenido fuera de una sección"),
    ("# PRIORITIES\n" + "".join(f"[P{i}] t{i}\n" for i in range(1, 7)), "como máximo cinco"),
    ("# PRIORITIES\n[P1] a\n[P1] b\n", "duplicadas"),
])
def test_invalid_input_raises(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        parse_daily(write(tmp_path, text))


def test_mitigation_does_not_carry_across_sections(tmp_path):
    with pytest.raises(ValueError, match="MITIGATION sin riesgo anterior"):
        parse_daily(write(tmp_path, "# RISKS\n- r\n# BLOCKERS\n-\n# RISKS\nMITIGATION: m\n"))
