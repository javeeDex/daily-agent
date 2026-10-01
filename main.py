import argparse
import json
import shutil
from datetime import date, datetime
from pathlib import Path
import yaml
from agent import DailyEmailAgent
from gmail import GmailDraft
from parser import parse_daily
from renderer import render_email
from asana import AsanaTasks

BASE = Path(__file__).resolve().parent

def config():
    return yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))

def target_date(value):
    if value:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    return date.today().isoformat()

def paths(cfg, day):
    return (BASE / cfg["daily"]["data_directory"] / f"{day}.md",
            BASE / cfg["daily"]["state_directory"] / f"{day}.json")

def init_file(data_file):
    if data_file.exists():
        raise SystemExit(f"Ya existe: {data_file}")
    data_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BASE / "daily-template.md", data_file)
    print(f"Creado: {data_file}")

def load_state(state_file):
    if not state_file.exists(): return {}
    try: return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError: return {}

def save_state(state_file, draft_id, subject):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"draft_id": draft_id, "subject": subject,
        "updated_at": datetime.now().astimezone().isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    p = argparse.ArgumentParser(description="Genera el daily y crea/actualiza un borrador de Gmail")
    p.add_argument("--date", help="YYYY-MM-DD; por defecto hoy")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--init", action="store_true", help="Crea el Markdown del día")
    mode.add_argument("--preview", action="store_true", help="Genera preview.html; no toca Gmail")
    mode.add_argument("--draft", action="store_true", help="Crea o actualiza el borrador Gmail del día")
    args = p.parse_args()
    cfg, day = config(), target_date(args.date)
    data_file, state_file = paths(cfg, day)
    if args.init:
        init_file(data_file); return
    if not data_file.exists():
        raise SystemExit(f"No existe {data_file}. Ejecuta: python main.py --init")
    parsed = parse_daily(data_file).to_dict()
    print(f"✓ Parseado {data_file.name}")
    asana_cfg = cfg.get("asana", {})
    if asana_cfg.get("enabled", False):
        print("[Asana] Integración activada.", flush=True)
        asana = AsanaTasks(
            asana_cfg.get("workspace_gid"),
            asana_cfg.get("timeout_seconds", 15),
        )
        parsed = asana.populate_due_today(parsed, day)
        parsed = asana.attach_links(parsed)
    else:
        print("[Asana] Integración desactivada (asana.enabled no es true).", flush=True)
    agent = DailyEmailAgent(
        BASE / "prompt.txt",
        cfg["llm"]["provider"],
        cfg["llm"]["model"],
        cfg["llm"].get("timeout_seconds", 120),
    )
    content = agent.generate(parsed)
    print("✓ Redacción generada")
    html = render_email(content)
    subject = cfg["email"]["subject"].format(date=day)
    if args.preview or not args.draft:
        out = BASE / "preview.html"
        out.write_text(html, encoding="utf-8")
        print(f"✓ Preview: {out}")
        if not args.preview:
            print("No se ha modificado Gmail. Usa --draft cuando quieras crear/actualizar el borrador.")
        return
    state = load_state(state_file)
    gmail = GmailDraft(BASE / "credentials" / "credentials.json", BASE / "token.json")
    draft, action = gmail.upsert(state.get("draft_id"), cfg["email"]["to"], subject, html,
                                 cfg["email"].get("cc"), cfg["email"].get("bcc"))
    save_state(state_file, draft["id"], subject)
    print(f"✓ Borrador {action}: {draft['id']}")
    print("No se ha enviado ningún email.")

if __name__ == "__main__":
    main()
