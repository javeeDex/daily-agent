import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "today": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category": {"type": "string"},
                    "tasks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["category", "tasks"],
            },
        },
        "priorities": {"type": "array", "items": {"type": "string"}},
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "risk": {"type": "string"},
                    "mitigation": {"type": "string"},
                },
                "required": ["risk", "mitigation"],
            },
        },
        "blockers": {"type": "array", "items": {"type": "string"}},
        "commitments": {"type": "string"},
        "growth": {"type": "string"},
    },
    "required": ["today", "priorities", "risks", "blockers", "commitments", "growth"],
}


class DailyEmailAgent:
    PROVIDERS = {
        "openai": ("OPENAI_API_KEY", "openai"),
        "gemini": ("GEMINI_API_KEY", "google-genai"),
        "claude": ("ANTHROPIC_API_KEY", "anthropic"),
    }

    def __init__(self, prompt_file: Path, provider: str, model: str, timeout_seconds: int = 120):
        self.provider = provider.strip().lower()
        if self.provider not in self.PROVIDERS:
            raise ValueError(
                f"Proveedor LLM no válido: {provider!r}. Usa uno de: openai, gemini, claude."
            )
        env_var, package = self.PROVIDERS[self.provider]
        api_key = os.getenv(env_var)
        if not api_key:
            raise RuntimeError(f"No se ha definido {env_var} en el entorno o en el archivo .env.")

        try:
            if self.provider == "gemini":
                from google import genai
                self.client = genai.Client(
                    api_key=api_key,
                    http_options=genai.types.HttpOptions(timeout=timeout_seconds * 1000),
                )
            elif self.provider == "openai":
                from openai import OpenAI
                self.client = OpenAI(api_key=api_key, timeout=timeout_seconds)
            else:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=api_key, timeout=timeout_seconds)
        except ImportError as exc:
            raise RuntimeError(
                f"Falta el SDK para {self.provider}. Instala las dependencias con: pip install -r requirements.txt"
            ) from exc

        self.timeout_seconds = timeout_seconds
        self.model = model
        self.instructions = prompt_file.read_text(encoding="utf-8")

    def generate(self, parsed: dict) -> dict:
        # print(f"✓ DATOS DEL DAILY YA PARSEADOS (fuente de verdad): {json.dumps(parsed, ensure_ascii=False, indent=2)}")

        prompt = (
            self.instructions
            + "\n\nDATOS DEL DAILY YA PARSEADOS (fuente de verdad):\n"
            + json.dumps(parsed, ensure_ascii=False, indent=2)
        )
        #print("✓ PROMPT PARA EL MODELO:\n", prompt)
        print(
            f"Consultando {self.provider} ({self.model}); tiempo máximo: {self.timeout_seconds}s...",
            flush=True,
        )
        started = time.perf_counter()
        try:
            if self.provider == "gemini":
                interaction = self.client.interactions.create(
                    model=self.model,
                    input=prompt,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": SCHEMA,
                    },
                )
                output_text = interaction.output_text
            elif self.provider == "openai":
                response = self.client.responses.create(
                    model=self.model,
                    instructions=self.instructions,
                    input="DATOS DEL DAILY YA PARSEADOS (fuente de verdad):\n"
                          + json.dumps(parsed, ensure_ascii=False, indent=2),
                    text={"format": {
                        "type": "json_schema",
                        "name": "daily_email",
                        "strict": True,
                        "schema": SCHEMA,
                    }},
                )
                output_text = response.output_text
            else:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.instructions,
                    messages=[{"role": "user", "content":
                               "DATOS DEL DAILY YA PARSEADOS (fuente de verdad):\n"
                               + json.dumps(parsed, ensure_ascii=False, indent=2)}],
                    output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
                )
                output_text = "".join(
                    block.text for block in response.content if getattr(block, "type", None) == "text"
                )
        finally:
            elapsed = time.perf_counter() - started
            #print(f"Petición a {self.provider} finalizada tras {elapsed:.1f} s.", flush=True)
        #print("✓ RESPUESTA DEL MODELO:\n", output_text)
        return json.loads(output_text)
