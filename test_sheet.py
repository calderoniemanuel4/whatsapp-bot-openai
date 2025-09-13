import os, time, gspread
from google.oauth2.service_account import Credentials

SHEET_ID = os.getenv("SHEET_ID","TU_ID")
CREDS = "service_account.json"

scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(CREDS, scopes=scopes)
client = gspread.authorize(creds)
sh = client.open_by_key(SHEET_ID).sheet1
ts = time.strftime("%Y-%m-%d %H:%M:%S")
sh.append_row([ts, "local-test", "hola", "respuesta"], value_input_option="RAW")
print("OK fila escrita")