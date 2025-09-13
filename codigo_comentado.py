# main.py — WhatsApp Bot (GCF Gen2) + Twilio + OpenAI + Google Sheets
# ---------------------------------------------------------------
# - Healthcheck con GET /
# - Comandos: /ping, /help, /code, /logtest
# - Persistencia en Google Sheets (ADC primero, luego JSON si se define)
# - Twilio responde en TwiML (XML)
# ---------------------------------------------------------------

import os
import time
import logging

from flask import Request, make_response
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI

# ---- Sheets deps
import gspread
import google.auth
from google.oauth2.service_account import Credentials

# ===== Config & Logging =====
logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger("whatsapp-bot")

# Vars de entorno (setear en deploy; defaults seguros para local)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SHEET_ID = os.getenv("SHEET_ID", "")                     # ID de tu Google Sheet (obligatorio en prod)
SHEETS_CREDS_FILE = os.getenv("SHEETS_CREDS_FILE", "service_account.json")  # fallback si no hay ADC
SHEET_TAB = os.getenv("SHEET_TAB", "")                   # opcional: nombre de la pestaña; vacío = sheet1

# Cliente OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Prompt base (triple comillas para legibilidad)
SYSTEM_PROMPT = """\
Eres Asistente Zen, un ayudante técnico amable y directo.
Responde en español, con precisión y en no más de 5–8 líneas salvo que te pidan más.
Cuando no tengas certeza, indícalo y sugiere una verificación simple.
"""

# ===== Helpers: OpenAI =====
def _ai_reply(text: str) -> str:
    """Respuesta conversacional estándar (texto libre)."""
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text or "(mensaje vacío)"},
            ],
            temperature=0.4,
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        logging.exception("OpenAI error: %s", e)
        return "No pude responder con IA ahora. Intenta de nuevo en unos segundos."

def _ai_code(user_prompt: str) -> str:
    """Genera SOLO código (sin explicaciones). Útil para /code."""
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """\
Eres un generador de snippets de código.
El usuario puede pedir código en Python, Bash, JavaScript, Swift, etc.
Responde SOLO con un bloque de código dentro de triple backticks.
No incluyas explicaciones ni texto fuera del bloque de código.
""",
                },
                {"role": "user", "content": user_prompt or "python: imprimir Hola Mundo"},
            ],
            temperature=0.2,
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        logging.exception("OpenAI /code error: %s", e)
        return "```txt\nNo pude generar el código ahora. Reintenta en unos segundos.\n```"

# ===== Helpers: Google Sheets =====
def _get_google_creds():
    """Obtiene credenciales: intenta ADC (identidad de la función). Si falla, usa archivo JSON."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",  # a veces necesario para open_by_key
    ]
    # 1) Application Default Credentials (recomendado en GCF)
    try:
        creds, proj = google.auth.default(scopes=scopes)
        log.info("Sheets: usando ADC. project=%s", proj)
        return creds
    except Exception as e:
        log.warning("Sheets: ADC no disponible (%s). Intento con archivo…", e)

    # 2) Fallback JSON (si subiste service_account.json y seteaste SHEETS_CREDS_FILE)
    try:
        creds_path = os.path.join(os.path.dirname(__file__), SHEETS_CREDS_FILE)
        log.info("Sheets: usando archivo %s", creds_path)
        return Credentials.from_service_account_file(creds_path, scopes=scopes)
    except Exception as e:
        logging.exception("Sheets: no se pudieron cargar credenciales: %s", e)
        raise

def _get_sheet():
    """Abre el spreadsheet por ID y retorna la worksheet objetivo."""
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID vacío. Define la variable de entorno SHEET_ID.")
    client = gspread.authorize(_get_google_creds())
    sh = client.open_by_key(SHEET_ID)
    ws = sh.worksheet(SHEET_TAB) if SHEET_TAB else sh.sheet1
    log.info("Sheets: abierto '%s' pestaña '%s'", sh.title, ws.title)
    return ws

def log_message(sender: str, body: str, reply: str):
    """Anexa una fila (timestamp, remitente, mensaje, respuesta)."""
    try:
        ws = _get_sheet()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        # Log visible previo a la escritura
        print(f"[SHEETS] append_row ts={ts} sender={sender} body_len={len(body)} reply_len={len(reply)}")
        ws.append_row([ts, sender or "-", body or "", reply or ""], value_input_option="RAW")
        log.info("Sheets OK: fila agregada.")
    except Exception as e:
        logging.exception("Error guardando en Sheets: %s", e)

# ===== HTTP Entry Point (GCF) =====
def webhook(request: Request):
    """
    - GET /            → healthcheck (200 ok)
    - GET /?debug=1    → escribe fila de prueba directo a Sheets
    - POST (Twilio)    → procesa /ping, /help, /logtest, /code, o chat normal; responde TwiML
    """
    # Healthcheck + modo diagnóstico
    if request.method != "POST":
        if request.args.get("debug") == "1":
            try:
                ws = _get_sheet()
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[SHEETS] DEBUG append_row ts={ts}")
                ws.append_row([ts, "debug", "GET ?debug=1", "fila de test"], value_input_option="RAW")
                logging.info("Sheets OK (debug): fila agregada.")
                return make_response("debug wrote row", 200)
            except Exception as e:
                logging.exception("Sheets DEBUG error: %s", e)
                return make_response(f"debug error: {e}", 500)
        return make_response("ok", 200)

    # ---- Flujo normal (Twilio manda form-encoded) ----
    body_orig = (request.form.get("Body") or "").strip()
    sender = request.form.get("From", "desconocido")
    t = body_orig.lower()

    # Router minimalista de comandos
    if t in {"ping", "/ping"}:
        reply = "pong"
    elif t in {"help", "/help", "ayuda", "/ayuda"}:
        reply = (
            "Comandos:\n"
            "• /ping — prueba rápida\n"
            "• /code <lenguaje> <instrucción> — responde SOLO con código\n"
            "• /logtest — prueba de escritura en Sheets\n"
        )
    elif t == "/logtest":
        log_message(sender, "[/logtest]", "OK log test")
        reply = "Log test ✅ (se intentó escribir en Sheets)."
    elif t.startswith("/code"):
        prompt = body_orig[len("/code"):].strip()
        reply = _ai_code(prompt or "python: imprimir Hola Mundo")
    elif not body_orig:
        reply = "Hola! Recibí tu mensaje vacío. Probá enviarme algo de texto 🙂"
    else:
        reply = _ai_reply(body_orig)

    # Log a Sheets para todo (salvo /logtest que ya lo hizo)
    if t != "/logtest":
        log_message(sender, body_orig, reply)

    # Construcción de TwiML (respuesta XML)
    tw = MessagingResponse()
    tw.message(reply or "")
    resp = make_response(str(tw), 200)
    resp.headers["Content-Type"] = "application/xml"
    return resp