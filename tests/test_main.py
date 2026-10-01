import json
import shutil
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import main

ROOT = Path(__file__).resolve().parent.parent
DAY = "2026-09-30"
CONTENT = {"today": [], "priorities": [], "risks": [], "blockers": [],
           "commitments": "c", "growth": "g"}


def make_cfg(asana_enabled=False):
    return {
        "email": {"to": ["to@x.com"], "cc": ["cc@x.com"], "bcc": [], "subject": "Journaling - {date}"},
        "daily": {"data_directory": "./data", "state_directory": "./state"},
        "llm": {"provider": "gemini", "model": "m", "timeout_seconds": 60},
        "asana": {"enabled": asana_enabled, "workspace_gid": "1", "timeout_seconds": 5},
    }


# --- small helpers -----------------------------------------------------------

def test_config_reads_project_yaml():
    cfg = main.config()
    assert {"email", "daily", "llm"} <= set(cfg)


def test_target_date_valid():
    assert main.target_date("2026-01-31") == "2026-01-31"


def test_target_date_defaults_to_today():
    assert main.target_date(None) == date.today().isoformat()


@pytest.mark.parametrize("value", ["2026-13-01", "30-09-2026", "hoy"])
def test_target_date_invalid(value):
    with pytest.raises(ValueError):
        main.target_date(value)


def test_paths():
    data_file, state_file = main.paths(make_cfg(), DAY)
    assert data_file == main.BASE / "./data" / f"{DAY}.md"
    assert state_file == main.BASE / "./state" / f"{DAY}.json"


def test_init_file_copies_template(tmp_path, monkeypatch):
    shutil.copyfile(ROOT / "daily-template.md", tmp_path / "daily-template.md")
    monkeypatch.setattr(main, "BASE", tmp_path)
    target = tmp_path / "nested" / "dir" / f"{DAY}.md"
    main.init_file(target)
    assert target.read_text() == (ROOT / "daily-template.md").read_text()


def test_init_file_refuses_to_overwrite(tmp_path):
    target = tmp_path / "x.md"
    target.write_text("mío")
    with pytest.raises(SystemExit, match="Ya existe"):
        main.init_file(target)
    assert target.read_text() == "mío"


def test_load_state_missing(tmp_path):
    assert main.load_state(tmp_path / "none.json") == {}


def test_load_state_corrupt(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{roto")
    assert main.load_state(path) == {}


def test_save_and_load_state_roundtrip(tmp_path):
    path = tmp_path / "state" / "s.json"
    main.save_state(path, "d1", "Asunto ñ")
    state = main.load_state(path)
    assert state["draft_id"] == "d1"
    assert state["subject"] == "Asunto ñ"
    assert "updated_at" in state
    assert "ñ" in path.read_text(encoding="utf-8")


# --- main() ------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Run main() inside a temp project with every external service mocked."""
    shutil.copyfile(ROOT / "daily-template.md", tmp_path / "daily-template.md")
    (tmp_path / "data").mkdir()
    shutil.copyfile(ROOT / "data" / "example.md", tmp_path / "data" / f"{DAY}.md")
    mocks = MagicMock()
    mocks.cfg = make_cfg()
    mocks.DailyEmailAgent.return_value.generate.return_value = CONTENT
    mocks.AsanaTasks.return_value.populate_due_today.side_effect = lambda parsed, day: {**parsed, "populated": True}
    mocks.AsanaTasks.return_value.attach_links.side_effect = lambda parsed: {**parsed, "linked": True}
    mocks.GmailDraft.return_value.upsert.return_value = ({"id": "draft-1"}, "created")
    monkeypatch.setattr(main, "BASE", tmp_path)
    monkeypatch.setattr(main, "config", lambda: mocks.cfg)
    for name in ("DailyEmailAgent", "AsanaTasks", "GmailDraft"):
        monkeypatch.setattr(main, name, getattr(mocks, name))
    mocks.tmp = tmp_path

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["main.py", "--date", DAY, *argv])
        main.main()

    mocks.run = run
    return mocks


def test_main_init_creates_file(env):
    (env.tmp / "data" / f"{DAY}.md").unlink()
    env.run("--init")
    assert (env.tmp / "data" / f"{DAY}.md").exists()
    env.DailyEmailAgent.assert_not_called()


def test_main_missing_daily_file_exits(env):
    (env.tmp / "data" / f"{DAY}.md").unlink()
    with pytest.raises(SystemExit, match="No existe"):
        env.run()


def test_main_invalid_date_fails(env, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--date", "nope"])
    with pytest.raises(ValueError):
        main.main()


def test_main_rejects_combined_modes(env):
    with pytest.raises(SystemExit):
        env.run("--preview", "--draft")


@pytest.mark.parametrize("flags", [(), ("--preview",)])
def test_main_preview_writes_html_without_gmail(env, flags):
    env.run(*flags)
    html = (env.tmp / "preview.html").read_text(encoding="utf-8")
    assert "Compromisos del día:</strong> c" in html
    env.GmailDraft.assert_not_called()
    env.DailyEmailAgent.assert_called_once_with(env.tmp / "prompt.txt", "gemini", "m", 60)
    parsed = env.DailyEmailAgent.return_value.generate.call_args.args[0]
    assert parsed["priorities"][0]["text"] == "Enviar propuesta Acciona Impact Lab"


def test_main_llm_timeout_defaults_to_120(env):
    del env.cfg["llm"]["timeout_seconds"]
    env.run("--preview")
    assert env.DailyEmailAgent.call_args.args[3] == 120


def test_main_asana_disabled(env):
    env.run("--preview")
    env.AsanaTasks.assert_not_called()


def test_main_asana_enabled(env):
    env.cfg["asana"]["enabled"] = True
    env.run("--preview")
    env.AsanaTasks.assert_called_once_with("1", 5)
    env.AsanaTasks.return_value.populate_due_today.assert_called_once()
    assert env.AsanaTasks.return_value.populate_due_today.call_args.args[1] == DAY
    parsed = env.DailyEmailAgent.return_value.generate.call_args.args[0]
    assert parsed["populated"] and parsed["linked"]


def test_main_draft_creates_and_saves_state(env):
    env.run("--draft")
    env.GmailDraft.assert_called_once_with(env.tmp / "credentials" / "credentials.json",
                                           env.tmp / "token.json")
    draft_id, to, subject, html, cc, bcc = env.GmailDraft.return_value.upsert.call_args.args
    assert draft_id is None
    assert to == ["to@x.com"]
    assert subject == f"Journaling - {DAY}"
    assert html.startswith("<!doctype html>")
    assert (cc, bcc) == (["cc@x.com"], [])
    state = json.loads((env.tmp / "state" / f"{DAY}.json").read_text())
    assert state["draft_id"] == "draft-1"
    assert not (env.tmp / "preview.html").exists()


def test_main_draft_reuses_saved_draft_id(env):
    main.save_state(env.tmp / "state" / f"{DAY}.json", "existing", "s")
    env.GmailDraft.return_value.upsert.return_value = ({"id": "existing"}, "updated")
    env.run("--draft")
    assert env.GmailDraft.return_value.upsert.call_args.args[0] == "existing"
