import io
import json
from urllib.error import HTTPError, URLError

import pytest

import asana
from asana import AsanaTasks, _score, _words


class FakeResponse:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ASANA_ACCESS_TOKEN", "tok")
    return AsanaTasks("123", timeout_seconds=5)


@pytest.fixture
def urlopen_calls(monkeypatch):
    """Patch urlopen; set `.responses` to a list of payloads or exceptions."""
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        result = fake_urlopen.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)

    fake_urlopen.responses = []
    fake_urlopen.calls = calls
    monkeypatch.setattr(asana, "urlopen", fake_urlopen)
    return fake_urlopen


# --- helpers -----------------------------------------------------------------

def test_words_filters_short_words_and_casefolds():
    assert _words("Revisar la Propuesta de TOUS") == {"revisar", "propuesta", "tous"}


def test_words_uses_link_label_not_url():
    assert _words("Ver [Invicta Finance](https://app.asana.com/x)") == {"ver", "invicta", "finance"}


def test_score_identical_is_one():
    assert _score("Propuesta Acciona", "propuesta acciona") == 1.0


def test_score_empty_is_zero():
    assert _score("", "algo") == 0.0
    assert _score("algo", "a b") == 0.0


def test_score_unrelated_is_low():
    assert _score("Propuesta Acciona", "Revisión mapa talento") < 0.55


# --- constructor -------------------------------------------------------------

def test_init_requires_token(monkeypatch):
    monkeypatch.delenv("ASANA_ACCESS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ASANA_ACCESS_TOKEN"):
        AsanaTasks("123")


def test_init_requires_workspace(monkeypatch):
    monkeypatch.setenv("ASANA_ACCESS_TOKEN", "tok")
    with pytest.raises(RuntimeError, match="workspace_gid"):
        AsanaTasks("")


def test_init_stores_workspace_as_string(monkeypatch):
    monkeypatch.setenv("ASANA_ACCESS_TOKEN", "tok")
    client = AsanaTasks(8432464193435)
    assert client.workspace_gid == "8432464193435"
    assert client.timeout_seconds == 15


# --- HTTP calls --------------------------------------------------------------

@pytest.mark.parametrize("method, arg, expected_params", [
    ("tasks_assigned_to_me_due_on", "2026-09-30",
     ["assignee.any=me", "due_on=2026-09-30", "completed=false", "limit=100"]),
    ("_search", "propuesta acciona", ["text=propuesta+acciona", "limit=20"]),
])
def test_requests_are_built_correctly(client, urlopen_calls, method, arg, expected_params):
    urlopen_calls.responses = [{"data": [{"name": "t"}]}]
    assert getattr(client, method)(arg) == [{"name": "t"}]
    request, timeout = urlopen_calls.calls[0]
    assert timeout == 5
    assert request.full_url.startswith(f"{asana.API_BASE}/workspaces/123/tasks/search?")
    assert request.get_header("Authorization") == "Bearer tok"
    for param in expected_params:
        assert param in request.full_url


def test_search_truncates_text_to_100_chars(client, urlopen_calls):
    urlopen_calls.responses = [{"data": []}]
    client._search("x" * 150)
    assert "text=" + "x" * 100 + "&" in urlopen_calls.calls[0][0].full_url


def test_missing_data_key_returns_empty_list(client, urlopen_calls):
    urlopen_calls.responses = [{}]
    assert client._search("algo") == []


@pytest.mark.parametrize("method", ["tasks_assigned_to_me_due_on", "_search"])
def test_http_error_is_wrapped(client, urlopen_calls, method):
    urlopen_calls.responses = [HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b"bad token"))]
    with pytest.raises(RuntimeError, match=r"HTTP 401\): bad token"):
        getattr(client, method)("x")


@pytest.mark.parametrize("method", ["tasks_assigned_to_me_due_on", "_search"])
def test_url_error_is_wrapped(client, urlopen_calls, method):
    urlopen_calls.responses = [URLError("timed out")]
    with pytest.raises(RuntimeError, match="No se pudo conectar con Asana: timed out"):
        getattr(client, method)("x")


# --- populate_due_today ------------------------------------------------------

def test_populate_fills_existing_asana_group(client, monkeypatch):
    monkeypatch.setattr(client, "tasks_assigned_to_me_due_on", lambda due_on: [
        {"name": "Con enlace", "permalink_url": "https://app.asana.com/1"},
        {"name": "Sin enlace"},
        {"permalink_url": "https://app.asana.com/ignored"},
    ])
    parsed = {"today": [
        {"category": "Consultoría", "tasks": ["x"]},
        {"category": "  tareas asana ", "tasks": ["old"]},
    ]}
    result = client.populate_due_today(parsed, "2026-09-30")
    assert result is parsed
    assert parsed["today"][1]["tasks"] == ["[Con enlace](https://app.asana.com/1)", "Sin enlace"]
    assert parsed["today"][0]["tasks"] == ["x"]


def test_populate_creates_group_first_when_missing(client, monkeypatch):
    monkeypatch.setattr(client, "tasks_assigned_to_me_due_on", lambda due_on: [])
    parsed = {"today": [{"category": "Equipo", "tasks": []}]}
    client.populate_due_today(parsed, "2026-09-30")
    assert parsed["today"][0] == {"category": "Tareas ASANA", "tasks": []}
    assert len(parsed["today"]) == 2


def test_populate_creates_today_when_absent(client, monkeypatch):
    monkeypatch.setattr(client, "tasks_assigned_to_me_due_on", lambda due_on: [{"name": "t"}])
    parsed = {}
    client.populate_due_today(parsed, "2026-09-30")
    assert parsed == {"today": [{"category": "Tareas ASANA", "tasks": ["t"]}]}


def test_populate_passes_date(client, monkeypatch):
    seen = []
    monkeypatch.setattr(client, "tasks_assigned_to_me_due_on", lambda due_on: seen.append(due_on) or [])
    client.populate_due_today({"today": []}, "2026-01-02")
    assert seen == ["2026-01-02"]


# --- attach_links ------------------------------------------------------------

def parsed_data():
    return {
        "today": [{"category": "Negocio", "tasks": ["Propuesta Acciona Impact"]}],
        "priorities": [{"priority": 1, "text": "Propuesta Acciona Impact"}],
        "commitments": ["Propuesta Acciona Impact", "Otra cosa distinta"],
    }


def fake_search(results_by_query):
    calls = []

    def search(query):
        calls.append(query)
        return results_by_query.get(query, [])

    search.calls = calls
    return search


def test_attach_links_links_clear_match_everywhere(client, monkeypatch):
    search = fake_search({"acciona impact propuesta": [
        {"name": "Propuesta Acciona Impact", "permalink_url": "https://app.asana.com/9"},
        {"name": "Algo sin relación", "permalink_url": "https://app.asana.com/8"},
    ]})
    monkeypatch.setattr(client, "_search", search)
    parsed = client.attach_links(parsed_data())
    linked = "Propuesta Acciona Impact [Asana](https://app.asana.com/9)"
    assert parsed["today"][0]["tasks"] == [linked]
    assert parsed["priorities"][0]["text"] == linked
    assert parsed["commitments"] == [linked, "Otra cosa distinta"]
    # Duplicated text is only searched once.
    assert search.calls.count("acciona impact propuesta") == 1


def test_attach_links_skips_items_with_existing_links(client, monkeypatch):
    search = fake_search({})
    monkeypatch.setattr(client, "_search", search)
    parsed = {"today": [{"category": "c", "tasks": ["Ya [enlace](https://x.com)"]}]}
    client.attach_links(parsed)
    assert search.calls == []


def test_attach_links_skips_items_without_words(client, monkeypatch):
    search = fake_search({})
    monkeypatch.setattr(client, "_search", search)
    client.attach_links({"today": [{"category": "c", "tasks": ["a b"]}]})
    assert search.calls == []


def test_attach_links_low_score_not_linked(client, monkeypatch):
    monkeypatch.setattr(client, "_search", lambda q: [
        {"name": "Revisión mapa talento", "permalink_url": "https://app.asana.com/1"},
    ])
    parsed = client.attach_links(parsed_data())
    assert parsed["today"][0]["tasks"] == ["Propuesta Acciona Impact"]


def test_attach_links_ambiguous_not_linked(client, monkeypatch):
    monkeypatch.setattr(client, "_search", lambda q: [
        {"name": "Propuesta Acciona Impact", "permalink_url": "https://app.asana.com/1"},
        {"name": "Propuesta Acciona Impact", "permalink_url": "https://app.asana.com/2"},
    ])
    parsed = client.attach_links(parsed_data())
    assert parsed["priorities"][0]["text"] == "Propuesta Acciona Impact"


def test_attach_links_match_without_permalink_not_linked(client, monkeypatch):
    monkeypatch.setattr(client, "_search", lambda q: [{"name": "Propuesta Acciona Impact"}])
    parsed = client.attach_links(parsed_data())
    assert parsed["commitments"][0] == "Propuesta Acciona Impact"


def test_attach_links_no_results(client, monkeypatch):
    monkeypatch.setattr(client, "_search", lambda q: [])
    assert client.attach_links(parsed_data()) == parsed_data()


def test_attach_links_propagates_search_errors(client, monkeypatch):
    def boom(query):
        raise RuntimeError("down")

    monkeypatch.setattr(client, "_search", boom)
    with pytest.raises(RuntimeError, match="down"):
        client.attach_links(parsed_data())


def test_attach_links_handles_empty_parsed(client, monkeypatch):
    monkeypatch.setattr(client, "_search", fake_search({}))
    assert client.attach_links({}) == {}
