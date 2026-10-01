"""Look up matching Asana tasks and attach their permalinks to daily items."""

import os
import re
import json
import time
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://app.asana.com/api/1.0"
WORD_RE = re.compile(r"[\w]{3,}", re.UNICODE)
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def _words(text):
    text = LINK_RE.sub(r"\1", text)
    return {word.casefold() for word in WORD_RE.findall(text)}


def _score(source, candidate):
    source_words, candidate_words = _words(source), _words(candidate)
    if not source_words or not candidate_words:
        return 0.0
    overlap = len(source_words & candidate_words) / len(source_words | candidate_words)
    sequence = SequenceMatcher(None, " ".join(sorted(source_words)),
                                " ".join(sorted(candidate_words))).ratio()
    return max(overlap, sequence * 0.8)


class AsanaTasks:
    def __init__(self, workspace_gid, timeout_seconds=15):
        self.token = os.getenv("ASANA_ACCESS_TOKEN")
        if not self.token:
            raise RuntimeError("Falta ASANA_ACCESS_TOKEN en el archivo .env")
        if not workspace_gid:
            raise RuntimeError("Configura asana.workspace_gid en config.yaml")
        self.workspace_gid = str(workspace_gid)
        self.timeout_seconds = timeout_seconds

    def tasks_assigned_to_me_due_on(self, due_on):
        """Return incomplete tasks assigned to the current user and due on a date."""
        params = urlencode({
            "assignee.any": "me",
            "due_on": due_on,
            "completed": "false",
            "opt_fields": "gid,name,permalink_url,due_on,assignee.name",
            "limit": 100,
        })
        request = Request(
            f"{API_BASE}/workspaces/{self.workspace_gid}/tasks/search?{params}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        print(
            f"[Asana] Consultando tareas asignadas a mí con vencimiento {due_on} "
            f"(workspace {self.workspace_gid})...",
            flush=True,
        )
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                results = json.loads(response.read().decode("utf-8")).get("data", [])
                elapsed = time.perf_counter() - started
                print(f"[Asana] HTTP {response.status}; {len(results)} tarea(s) devuelta(s) en {elapsed:.2f}s.", flush=True)
                return results
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - started
            print(f"[Asana] HTTP {exc.code} tras {elapsed:.2f}s.", flush=True)
            raise RuntimeError(f"Error de Asana (HTTP {exc.code}): {detail}") from exc
        except URLError as exc:
            elapsed = time.perf_counter() - started
            print(f"[Asana] Error de conexión tras {elapsed:.2f}s: {exc.reason}", flush=True)
            raise RuntimeError(f"No se pudo conectar con Asana: {exc.reason}") from exc

    def populate_due_today(self, parsed, due_on):
        """Fill the TODAY category named 'Tareas ASANA' with today's assigned tasks."""
        tasks = self.tasks_assigned_to_me_due_on(due_on)
        asana_group = next(
            (group for group in parsed.get("today", [])
             if group.get("category", "").strip().casefold() == "tareas asana"),
            None,
        )
        if asana_group is None:
            asana_group = {"category": "Tareas ASANA", "tasks": []}
            parsed.setdefault("today", []).insert(0, asana_group)

        asana_group["tasks"] = [
            f"[{task['name']}]({task['permalink_url']})" if task.get("permalink_url") else task["name"]
            for task in tasks if task.get("name")
        ]
        for task in tasks:
            if task.get("name"):
                link = f" -> {task['permalink_url']}" if task.get("permalink_url") else " (sin enlace)"
                print(
                    f"[Asana] Tarea para incluir: {task['name']!r} "
                    f"(vencimiento {task.get('due_on', due_on)})"
                    f"{link}",
                    flush=True,
                )
        if not tasks:
            print(f"[Asana] No hay tareas incompletas asignadas a ti con vencimiento {due_on}.", flush=True)
        print(f"[Asana] Se han añadido {len(asana_group['tasks'])} tarea(s) a 'Tareas ASANA'.", flush=True)
        return parsed

    def _search(self, text):
        params = urlencode({
            "text": text[:100],
            "opt_fields": "gid,name,permalink_url",
            "limit": 20,
        })
        request = Request(
            f"{API_BASE}/workspaces/{self.workspace_gid}/tasks/search?{params}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        print(f"[Asana] Buscando en workspace {self.workspace_gid}: {text!r}", flush=True)
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                results = json.loads(response.read().decode("utf-8")).get("data", [])
                elapsed = time.perf_counter() - started
                print(f"[Asana] HTTP {response.status}; {len(results)} resultado(s) en {elapsed:.2f}s.", flush=True)
                return results
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - started
            print(f"[Asana] HTTP {exc.code} tras {elapsed:.2f}s.", flush=True)
            raise RuntimeError(f"Error de Asana (HTTP {exc.code}): {detail}") from exc
        except URLError as exc:
            elapsed = time.perf_counter() - started
            print(f"[Asana] Error de conexión tras {elapsed:.2f}s: {exc.reason}", flush=True)
            raise RuntimeError(f"No se pudo conectar con Asana: {exc.reason}") from exc

    def attach_links(self, parsed):
        """Attach a link only when one result is a sufficiently clear text match."""
        items = []
        for group in parsed.get("today", []):
            items.extend(group.get("tasks", []))
        items.extend(p["text"] for p in parsed.get("priorities", []))
        items.extend(parsed.get("commitments", []))

        cache = {}
        processed = set()
        linked = 0
        for text in items:
            if text in processed or LINK_RE.search(text):
                continue
            processed.add(text)
            query = " ".join(sorted(_words(text)))
            if not query:
                print(f"[Asana] Sin palabras de búsqueda: {text!r}", flush=True)
                continue
            if query not in cache:
                try:
                    cache[query] = self._search(query)
                except RuntimeError as exc:
                    print(f"[Asana] Falló la búsqueda para {text!r}: {exc}", flush=True)
                    raise
            candidates = cache[query]
            ranked = sorted(
                ((_score(text, task.get("name", "")), task) for task in candidates),
                key=lambda item: item[0], reverse=True,
            )
            if not ranked:
                print(f"[Asana] Sin resultados para: {text!r}", flush=True)
                continue
            best_score, best_task = ranked[0]
            preview = "; ".join(
                f"{task.get('name', '(sin nombre)')!r} ({score:.2f})"
                for score, task in ranked[:3]
            )
            print(f"[Asana] Elemento: {text!r}. Candidatos: {preview}", flush=True)
            if best_score < 0.55:
                print(f"[Asana] No se enlaza: mejor puntuación {best_score:.2f} < 0.55.", flush=True)
                continue
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
                print("[Asana] No se enlaza: coincidencia ambigua entre los mejores candidatos.", flush=True)
                continue  # Ambiguous: don't risk attaching the wrong task.
            task = best_task
            url = task.get("permalink_url")
            if not url:
                print(f"[Asana] No se enlaza {task.get('name')!r}: respuesta sin permalink_url.", flush=True)
                continue
            linked_text = f"{text} [Asana]({url})"
            for group in parsed.get("today", []):
                group["tasks"] = [linked_text if item == text else item for item in group.get("tasks", [])]
            for priority in parsed.get("priorities", []):
                if priority["text"] == text:
                    priority["text"] = linked_text
            parsed["commitments"] = [linked_text if item == text else item
                                     for item in parsed.get("commitments", [])]
            linked += 1
            print(f"[Asana] Coincidencia aceptada ({best_score:.2f}): {task.get('name')!r} -> {url}", flush=True)
        print(f"[Asana] Resumen: añadidos enlaces a {linked} elemento(s).", flush=True)
        return parsed
