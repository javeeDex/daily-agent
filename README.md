# Daily Email Agent — OpenAI / Gemini / Claude + Gmail

Genera el email daily a partir de un Markdown editado con Neovim. El proveedor LLM elegido solo redacta/normaliza el contenido ya parseado; el programa genera HTML y crea o actualiza **un borrador de Gmail**, nunca lo envía.

## Flujo

`Neovim -> Markdown -> parser.py -> OpenAI / Gemini / Claude -> renderer.py -> Gmail Draft`

El Markdown sigue siendo la fuente de verdad: `TODAY`, prioridades `[P1]..[P5]`, `RISKS` + `MITIGATION:`, `BLOCKERS`, `COMMITMENTS` y `GROWTH`.

## 1. Crear entorno

```bash
cd ~/daily-email-agent
python3 -m venv .venv
```

Bash/Zsh:

```bash
source .venv/bin/activate
```

Fish:

```fish
source .venv/bin/activate.fish
```

También puedes no activar el entorno y ejecutar siempre `.venv/bin/python` y `.venv/bin/pip`.

## 2. Dependencias

```bash
.venv/bin/pip install -r requirements.txt
```

Se instalan los SDK oficiales de los tres proveedores (`openai`, `google-genai` y `anthropic`). Solo se inicializa el SDK del proveedor elegido en la configuración.

## 3. Elegir proveedor y configurar API key

```bash
cp .env.example .env
nvim .env
```

Contenido:

```env
GEMINI_API_KEY=TU_CLAVE_REAL
OPENAI_API_KEY=TU_CLAVE_REAL
ANTHROPIC_API_KEY=TU_CLAVE_REAL
```

Añade la clave del proveedor que vayas a utilizar; no es necesario configurar las tres. En `config.yaml`, selecciona el proveedor, el modelo disponible en tu cuenta y el timeout:

```yaml
llm:
  provider: "gemini" # openai, gemini o claude
  model: "gemini-3.8-flash"
  timeout_seconds: 120
```

Para cambiar, modifica `provider`, `model` y usa la variable correspondiente: `OPENAI_API_KEY`, `GEMINI_API_KEY` o `ANTHROPIC_API_KEY` (para Claude). El nombre de configuración `claude` usa el SDK de Anthropic.

Protege el fichero:

```bash
chmod 600 .env
```

No subas `.env` a Git. Comprueba que el nombre de modelo configurado esté disponible para la API key elegida.

## 4. Configurar destinatarios

Edita `config.yaml`:

```yaml
email:
  to:
    - "persona@empresa.com"
  cc: []
  bcc: []
  subject: "Daily - {date}"
```

## 5. Crear el daily

```bash
.venv/bin/python main.py --init
nvim data/$(date +%F).md
```

Ejemplo:

```markdown
# TODAY

## Consultoría
- Entrevista candidatos [Accenture - Lucia Vicente](https://app.asana.com/...)

## Desarrollo de negocio
- Revisar propuesta [Invicta Finance](https://app.asana.com/...)

# PRIORITIES

[P1] Enviar propuesta Acciona Impact Lab
[P2] Ganar propuesta Onboarding Bestinver
[P3] Validar perfiles Accenture
[P4] Acelerar propuestas TOUS, Finocio y Acciona
[P5] Diseñar Business Case Digital Asset

# RISKS

- Lentitud en respuesta de algunas leads
  MITIGATION: Reuniones convocadas hoy para acelerar

# BLOCKERS

-

# COMMITMENTS

- Entregar propuesta actualizada de Onboarding Digital (Bestinver)
- Seguir diagnóstico SDLC y SDD

# GROWTH

- Entender mejor al equipo y sus capacidades para diseñar una mejor estrategia de innovación
```

## 6. Preview — primera prueba recomendada

```bash
.venv/bin/python main.py --preview
xdg-open preview.html
```

Esto llama al proveedor LLM configurado pero **no toca Gmail**.

## 7. Enlaces automáticos de Asana (opcional)

El programa consulta Asana para rellenar la categoría `## Tareas ASANA` de
`TODAY` con tareas incompletas asignadas al usuario autenticado y cuya fecha de
vencimiento coincide con el día del daily. Cada tarea incluye un enlace a
Asana. También puede adjuntar enlaces a actividades, prioridades y compromisos
escritos manualmente cuando encuentra una coincidencia clara; los enlaces
manuales se respetan.

1. Crea un Personal Access Token de Asana con acceso de lectura y añádelo a
   `.env` (no lo compartas ni lo subas a Git):

   ```env
   ASANA_ACCESS_TOKEN=tu_token
   ```

2. Obtén el GID del workspace y configura `config.yaml`:

   ```yaml
   asana:
     enabled: true
     workspace_gid: "GID_DEL_WORKSPACE"
     timeout_seconds: 15
   ```

La plantilla incluye `## Tareas ASANA`; si la categoría no existe en un daily
antiguo, se añade al principio de `TODAY`. Al ejecutar con `--date`, se buscan
tareas cuya fecha de vencimiento sea esa fecha.

La búsqueda se realiza durante `--preview` y `--draft`, antes de pedirle a
Gemini que redacte. Primero prueba con `--preview` y revisa los enlaces. Si no
configuras Asana, la integración permanece desactivada.

## 8. Configurar Gmail API

En Google Cloud crea/selecciona un proyecto, habilita Gmail API, configura OAuth y crea credenciales OAuth de tipo **Desktop application**. Descarga el JSON como:

`credentials/credentials.json`

La primera ejecución de `--draft` abrirá el navegador para autorizar Gmail y creará `token.json`.

El código solicita el scope `gmail.compose` y no contiene ninguna llamada a `drafts.send`.

## 9. Crear/actualizar borrador

```bash
.venv/bin/python main.py --draft
```

La primera vez crea el borrador y guarda su ID en `state/YYYY-MM-DD.json`. Las siguientes ejecuciones del mismo día actualizan ese mismo borrador. Si lo borraste manualmente en Gmail, el programa crea uno nuevo.

## 10. Otras fechas

```bash
.venv/bin/python main.py --date 2026-09-29 --init
.venv/bin/python main.py --date 2026-09-29 --preview
.venv/bin/python main.py --date 2026-09-29 --draft
```

## 11. systemd

Se incluyen `systemd/daily-email.service` y `systemd/daily-email.timer`. Revisa primero rutas y horario antes de instalarlos. Para este proyecto se recomienda probar manualmente `--preview` y `--draft` antes de activar el timer.

## Seguridad

- `.env`, `token.json` y `credentials/` están excluidos de Git.
- El token de Asana solo se usa para leer títulos y enlaces de tareas del workspace configurado.
- No existe opción `--send`.
- El proveedor LLM seleccionado recibe el contenido del daily para redactarlo; revisa las políticas corporativas aplicables a los datos que introduzcas.
- Gmail solo se modifica cuando ejecutas `--draft`.
