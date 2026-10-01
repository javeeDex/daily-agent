# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI that turns a hand-written daily Markdown file (`data/YYYY-MM-DD.md`) into an HTML work email and creates/updates a **Gmail draft** — it never sends. User-facing strings, CLI messages, prompt and README are in Spanish; keep new user-facing text in Spanish.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # dev deps (includes pytest)

.venv/bin/python main.py --init              # copy daily-template.md -> data/<today>.md
.venv/bin/python main.py --preview           # parse + Asana + LLM -> preview.html (no Gmail)
.venv/bin/python main.py --draft             # same, then create/update Gmail draft
.venv/bin/python main.py --date 2026-09-29 --preview   # any mode for another day

.venv/bin/pytest                             # all tests (testpaths = tests)
.venv/bin/pytest tests/test_parser.py::test_name       # single test
```

Running with no mode flag behaves like `--preview`. Tests mock all LLM SDKs, Asana HTTP and Gmail — they need no keys or network. `tests/conftest.py` puts the repo root on `sys.path` so modules are imported flat (`import main`, `import agent`).

## Pipeline

`main.py` orchestrates: `parser.parse_daily` → optional `asana.AsanaTasks` enrichment → `agent.DailyEmailAgent.generate` → `renderer.render_email` → `preview.html` or `gmail.GmailDraft.upsert`.

- **The Markdown is the source of truth; the LLM only rewords.** `parser.py` decides section membership and priority order (strict: unknown `# ` sections, tasks before a `##` category in TODAY, malformed `[Pn]`, >5 or duplicate priorities, orphan `MITIGATION:` all raise `ValueError`). `prompt.txt` forbids the model from adding/removing/reordering content or altering URLs. Preserve this division of responsibility when changing either side.
- **Data shape changes between stages.** Parser output has `commitments`/`growth` as lists and `priorities` as `{priority, text}` dicts; the LLM output (`agent.SCHEMA`, strict JSON schema, all fields required) has `commitments`/`growth` as single strings and `priorities` as plain strings. `renderer.py` consumes the LLM shape. Changing the schema means updating `SCHEMA`, `prompt.txt`, `renderer.py` and tests together.
- **LLM providers** (`llm.provider` in `config.yaml`: `openai` | `gemini` | `claude`): only the selected SDK is imported lazily in `DailyEmailAgent.__init__`. Each provider uses its own structured-output API (Gemini `interactions.create` with `response_format`, OpenAI `responses.create` with `json_schema`, Anthropic `messages.create` with `output_config`). API keys come from `.env` via `python-dotenv` (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`).
- **Asana** (`asana.enabled`, `ASANA_ACCESS_TOKEN`): uses stdlib `urllib`, no SDK. `populate_due_today` overwrites the `## Tareas ASANA` TODAY category (inserting it first if missing) with the user's incomplete tasks due on the daily's date. `attach_links` fuzzy-matches unlinked TODAY/priority/commitment items against Asana search results and appends `[Asana](url)` only when score ≥ 0.55 and the lead over the runner-up is ≥ 0.08; items already containing a Markdown link are skipped.
- **Links** travel as Markdown `[label](url)` through the whole pipeline; `renderer.markdown_to_html` converts them and HTML-escapes everything else.
- **Gmail** uses only the `gmail.compose` scope (OAuth desktop flow, `credentials/credentials.json` → `token.json`). The draft ID per day is stored in `state/YYYY-MM-DD.json`; re-running `--draft` updates that draft, and a 404 falls back to creating a new one. There is deliberately no send path — don't add one.

`systemd/` contains a user service + Mon–Fri 18:00 timer running `--draft`; its paths assume `~/daily-email-agent`.
