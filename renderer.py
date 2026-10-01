from html import escape
import re

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

def markdown_to_html(text: str) -> str:
    result, pos = [], 0
    for m in LINK_RE.finditer(text):
        result.append(escape(text[pos:m.start()]))
        label, url = m.groups()
        result.append(f'<a href="{escape(url, quote=True)}">{escape(label)}</a>')
        pos = m.end()
    result.append(escape(text[pos:]))
    return "".join(result)

def render_list(items):
    if not items:
        return "<ul><li>-</li></ul>"
    return "<ul>" + "".join(f"<li>{markdown_to_html(x)}</li>" for x in items) + "</ul>"

def render_email(data):
    today = "<ul>"
    for group in data["today"]:
        today += f"<li><strong>{escape(group['category'])}</strong>{render_list(group['tasks'])}</li>"
    today += "</ul>"
    risks = []
    for r in data["risks"]:
        text = r["risk"]
        if r.get("mitigation"):
            text += f". Mitigación: {r['mitigation']}"
        risks.append(text)
    blockers = data["blockers"] or ["Ninguno identificado por el momento!"]
    return f'''<!doctype html><html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#222">
<p>Hola,</p>
<p>Os envío el journaling de hoy:</p>
<p><strong>Qué haré hoy</strong></p>{today}
<p><strong>Top 5 prioridades</strong></p>{render_list(data['priorities'])}
<p><strong>Riesgos detectados</strong></p>{render_list(risks)}
<p><strong>Bloqueos</strong></p>{render_list(blockers)}
<p><strong>Compromisos del día:</strong> {markdown_to_html(data['commitments'] or '-')}</p>
<p><strong>Cómo ayuda mis compromisos al crecimiento en Rol/Líder:</strong> {markdown_to_html(data['growth'] or '-')}</p>
<p>Saludos,</p>
</body></html>'''
