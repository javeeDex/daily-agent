import re
from dataclasses import dataclass, asdict
from pathlib import Path

SECTIONS = {"TODAY", "PRIORITIES", "RISKS", "BLOCKERS", "COMMITMENTS", "GROWTH"}

@dataclass
class DailyData:
    today: list
    priorities: list
    risks: list
    blockers: list
    commitments: list
    growth: list

    def to_dict(self):
        return asdict(self)


def _clean_bullet(line: str) -> str:
    return re.sub(r"^\s*-\s*", "", line).strip()


def parse_daily(path: Path) -> DailyData:
    lines = path.read_text(encoding="utf-8").splitlines()
    section = None
    category = None
    today = []
    priorities = []
    risks = []
    blockers = []
    commitments = []
    growth = []
    current_risk = None

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("# "):
            name = stripped[2:].strip().upper()
            if name not in SECTIONS:
                raise ValueError(f"Sección desconocida: {name}")
            section = name
            category = None
            current_risk = None
            continue

        if section == "TODAY" and stripped.startswith("## "):
            category = stripped[3:].strip()
            today.append({"category": category, "tasks": []})
            continue

        if section == "TODAY":
            if not category:
                raise ValueError("TODAY contiene una tarea antes de una categoría ##")
            item = _clean_bullet(stripped)
            if item and item != "-":
                today[-1]["tasks"].append(item)

        elif section == "PRIORITIES":
            m = re.match(r"^\[P([1-9]\d*)\]\s*(.+)$", stripped, re.I)
            if not m:
                raise ValueError(f"Prioridad inválida: {stripped}. Usa [P1] texto")
            value = m.group(2).strip()
            if value != "-":
                priorities.append({"priority": int(m.group(1)), "text": value})

        elif section == "RISKS":
            if re.match(r"^MITIGATION\s*:", stripped, re.I):
                if current_risk is None:
                    raise ValueError("MITIGATION sin riesgo anterior")
                current_risk["mitigation"] = re.sub(r"^MITIGATION\s*:\s*", "", stripped, flags=re.I)
            else:
                item = _clean_bullet(stripped)
                if item and item != "-":
                    current_risk = {"risk": item, "mitigation": ""}
                    risks.append(current_risk)

        elif section == "BLOCKERS":
            item = _clean_bullet(stripped)
            if item and item != "-":
                blockers.append(item)

        elif section == "COMMITMENTS":
            item = _clean_bullet(stripped)
            if item and item != "-":
                commitments.append(item)

        elif section == "GROWTH":
            item = _clean_bullet(stripped)
            if item and item != "-":
                growth.append(item)

        else:
            raise ValueError(f"Contenido fuera de una sección: {stripped}")

    priorities.sort(key=lambda x: x["priority"])
    if len(priorities) > 5:
        raise ValueError("TOP 5 admite como máximo cinco prioridades")
    nums = [p["priority"] for p in priorities]
    if len(nums) != len(set(nums)):
        raise ValueError("Hay prioridades P duplicadas")

    return DailyData(today, priorities, risks, blockers, commitments, growth)
