"""
# REPOSITORIO EN Git
https://github.com/calderoniemanuel4/whatsapp-bot-openai.git

# Configurá tus datos:
PROJECT_ID="whatsapp-bot-emanuel"           # ← reemplazá por tu ID en GCP
REGION="us-central1"               # región donde desplegar
FUNCTION_NAME="whatsapp-bot-v2"       # nombre de la función


# 🚀 Ejecuta el deploy
gcloud config set project "$PROJECT_ID"
gcloud functions deploy whatsapp-bot-v2 \
  --gen2 \
  --region=us-central1 \
  --runtime=python312 \
  --entry-point=webhook \
  --trigger-http \
  --allow-unauthenticated \
  --source . \
  --set-env-vars=OPENAI_API_KEY=sk-XXXX,OPENAI_MODEL=gpt-4o-mini,SHEET_ID=1R...

Si se ejecuta local las KEYS de openai, twillio y SHEET_ID deben definirse en el archivo .env
y las CREDS de google sheets en service_account.json
Si se ejecuta en la nube las KEYS se setean en el deploy y las creds las obtiene del service account de la funcion.
"""

import os, time, logging
from flask import Request, make_response
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
import google.auth

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "Eres Asistente Zen, un ayudante técnico amable y directo. Responde en español, "
    "concretamente y en un máximo de 5-8 líneas salvo que te pidan más."
)

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger("sheets")

# Cargar credenciales desde JSON (guardado como secret en GCF)
SHEETS_CREDS_FILE = "service_account.json"
SHEET_ID = os.getenv("SHEET_ID", "")

def _get_google_creds():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",  # a veces hace falta para abrir por clave
    ]
    # 1) ADC (sin JSON)
    try:
        creds, proj = google.auth.default(scopes=scopes)
        log.info("Sheets: usando ADC. project=%s", proj)
        return creds
    except Exception as e:
        log.warning("Sheets: ADC no disponible (%s). Intento con archivo…", e)

    # 2) JSON (fallback)
    try:
        creds_path = os.path.join(os.path.dirname(__file__), SHEETS_CREDS_FILE)
        log.info("Sheets: intentando archivo %s", creds_path)
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        return creds
    except Exception as e:
        log.exception("Sheets: no se pudieron cargar credenciales: %s", e)
        raise

def _get_sheet():
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID vacío")
    creds = _get_google_creds()
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    log.info("Sheets: abierto spreadsheet '%s'", sh.title)
    ws = sh.sheet1  # si tu pestaña no es la primera, usa .worksheet("Nombre")
    log.info("Sheets: usando worksheet '%s'", ws.title)
    return ws

def log_message(sender: str, body: str, reply: str):
    try:
        ws = _get_sheet()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([ts, sender or "-", body or "", reply or ""], value_input_option="RAW")
        log.info("Sheets OK: fila agregada.")
    except Exception as e:
        log.exception("Error guardando en Sheets: %s", e)

def _ai_code(text: str) -> str:
    """Genera código puro a partir del prompt del usuario."""
    try:
        r = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Eres un generador de snippets de código. "
                    "El usuario puede pedir código en Python, Bash, JS, etc. "
                    "Responde SOLO con un bloque de código válido, sin explicaciones."
                )},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Ups, no pude generar el código: {e}"

def _ai_reply(text: str) -> str:
    try:
        r = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text or "(mensaje vacío)"},
            ],
            temperature=0.4,
        )
        return (r.choices[0].message.content or "No pude generar respuesta.").strip()
    except Exception as e:
        return f"Ups, hubo un error consultando a IA: {e}"

def webhook(request: Request):
    # Healthcheck y diagnóstico
    if request.method != "POST":
        # Forzar escritura directa: GET /?debug=1
        if request.args.get("debug") == "1":
            try:
                ws = _get_sheet()
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                ws.append_row([ts, "debug", "GET /?debug=1", "fila de test"], value_input_option="RAW")
                logging.info("Sheets OK (debug): fila agregada.")
                return make_response("debug wrote row", 200)
            except Exception as e:
                logging.exception("Sheets DEBUG error: %s", e)
                return make_response(f"debug error: {e}", 500)
        return make_response("ok", 200)

    # --- Flujo normal Twilio ---
    body_orig = (request.form.get("Body") or "").strip()
    t = body_orig.lower()

    if t in {"ping", "/ping"}:
        reply = "pong"
    elif t in {"help", "/help", "ayuda", "/ayuda"}:
        reply = "Comandos: /ping, /help, /code <lenguaje> <instrucción>"
    elif t.startswith("/code"):
        prompt = body_orig[len("/code"):].strip()
        reply = _ai_code(prompt or "python ejemplo básico")
    elif not body_orig:
        reply = "Hola! Recibí tu mensaje vacío. Probá enviarme algo de texto 🙂"
    else:
        reply = _ai_reply(body_orig)

    # Log a Sheets
    sender = request.form.get("From", "desconocido")
    log_message(sender, body_orig, reply)

    tw = MessagingResponse()
    tw.message(reply or "")
    resp = make_response(str(tw), 200)
    resp.headers["Content-Type"] = "application/xml"
    return resp
