import json
import sys
import types
from unittest.mock import MagicMock

import pytest

import agent
from agent import SCHEMA, DailyEmailAgent

PARSED = {"today": [{"category": "IA", "tasks": ["Probar ñ"]}]}
OUTPUT = {"today": [], "priorities": [], "risks": [], "blockers": [],
          "commitments": "c", "growth": "g"}


@pytest.fixture
def prompt_file(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("INSTRUCCIONES", encoding="utf-8")
    return path


@pytest.fixture
def sdks(monkeypatch):
    """Install fake SDK modules so no real client or network is used."""
    fakes = types.SimpleNamespace(genai=MagicMock(), openai=MagicMock(), anthropic=MagicMock())
    import google
    monkeypatch.setitem(sys.modules, "google.genai", fakes.genai)
    monkeypatch.setattr(google, "genai", fakes.genai, raising=False)
    monkeypatch.setitem(sys.modules, "openai", fakes.openai)
    monkeypatch.setitem(sys.modules, "anthropic", fakes.anthropic)
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(var, f"key-{var}")
    return fakes


def test_schema_requires_all_fields():
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])


# --- constructor -------------------------------------------------------------

def test_invalid_provider(prompt_file):
    with pytest.raises(ValueError, match="Proveedor LLM no válido"):
        DailyEmailAgent(prompt_file, "mistral", "m")


@pytest.mark.parametrize("provider, env_var", [
    ("openai", "OPENAI_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("claude", "ANTHROPIC_API_KEY"),
])
def test_missing_api_key(prompt_file, monkeypatch, provider, env_var):
    monkeypatch.delenv(env_var, raising=False)
    with pytest.raises(RuntimeError, match=env_var):
        DailyEmailAgent(prompt_file, provider, "m")


def test_provider_is_normalized(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "  OpenAI ", "gpt", timeout_seconds=30)
    assert a.provider == "openai"
    assert a.model == "gpt"
    assert a.timeout_seconds == 30
    assert a.instructions == "INSTRUCCIONES"


def test_gemini_client(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "gemini", "g", timeout_seconds=10)
    sdks.genai.types.HttpOptions.assert_called_once_with(timeout=10_000)
    sdks.genai.Client.assert_called_once_with(
        api_key="key-GEMINI_API_KEY", http_options=sdks.genai.types.HttpOptions.return_value)
    assert a.client is sdks.genai.Client.return_value


def test_openai_client(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "openai", "o", timeout_seconds=10)
    sdks.openai.OpenAI.assert_called_once_with(api_key="key-OPENAI_API_KEY", timeout=10)
    assert a.client is sdks.openai.OpenAI.return_value


def test_claude_client(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "claude", "c", timeout_seconds=10)
    sdks.anthropic.Anthropic.assert_called_once_with(api_key="key-ANTHROPIC_API_KEY", timeout=10)
    assert a.client is sdks.anthropic.Anthropic.return_value


def test_missing_sdk(prompt_file, sdks, monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)  # makes the import fail
    with pytest.raises(RuntimeError, match="Falta el SDK para openai"):
        DailyEmailAgent(prompt_file, "openai", "o")


# --- generate ----------------------------------------------------------------

def expected_input():
    return "DATOS DEL DAILY YA PARSEADOS (fuente de verdad):\n" + json.dumps(
        PARSED, ensure_ascii=False, indent=2)


def test_generate_gemini(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "gemini", "gem")
    a.client.interactions.create.return_value.output_text = json.dumps(OUTPUT)
    assert a.generate(PARSED) == OUTPUT
    kwargs = a.client.interactions.create.call_args.kwargs
    assert kwargs["model"] == "gem"
    assert kwargs["input"] == "INSTRUCCIONES\n\n" + expected_input()
    assert "Probar ñ" in kwargs["input"]
    assert kwargs["response_format"]["schema"] is SCHEMA
    assert kwargs["response_format"]["mime_type"] == "application/json"


def test_generate_openai(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "openai", "gpt")
    a.client.responses.create.return_value.output_text = json.dumps(OUTPUT)
    assert a.generate(PARSED) == OUTPUT
    kwargs = a.client.responses.create.call_args.kwargs
    assert kwargs["model"] == "gpt"
    assert kwargs["instructions"] == "INSTRUCCIONES"
    assert kwargs["input"] == expected_input()
    fmt = kwargs["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] is SCHEMA


def test_generate_claude_joins_text_blocks(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "claude", "claude-model")
    text = json.dumps(OUTPUT)
    a.client.messages.create.return_value.content = [
        types.SimpleNamespace(type="thinking", text="ignored"),
        types.SimpleNamespace(type="text", text=text[:10]),
        types.SimpleNamespace(type="text", text=text[10:]),
    ]
    assert a.generate(PARSED) == OUTPUT
    kwargs = a.client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-model"
    assert kwargs["system"] == "INSTRUCCIONES"
    assert kwargs["messages"] == [{"role": "user", "content": expected_input()}]
    assert kwargs["output_config"]["format"]["schema"] is SCHEMA


def test_generate_invalid_json_raises(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "openai", "gpt")
    a.client.responses.create.return_value.output_text = "no es json"
    with pytest.raises(json.JSONDecodeError):
        a.generate(PARSED)


def test_generate_propagates_client_errors(prompt_file, sdks):
    a = DailyEmailAgent(prompt_file, "openai", "gpt")
    a.client.responses.create.side_effect = TimeoutError("slow")
    with pytest.raises(TimeoutError):
        a.generate(PARSED)
