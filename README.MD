# WhatsApp Bot en Google Cloud Functions (Gen2)

Bot de WhatsApp usando **Twilio Sandbox** + **OpenAI** desplegado en **Google Cloud Functions**.

---

## ✅ Checklist de Deploy

### 1. Archivos del proyecto
- [ ] Crear `requirements.txt` con:
  ```txt
  functions-framework==3.5.0
  twilio==9.3.3
  openai==1.50.2
  httpx==0.27.2   # fijar versión para evitar error de proxies

 ### 2. Configuración de GCP
	•	Seleccionar proyecto en la consola web o crear uno nuevo.
	•	Configurar en terminal:
    gcloud config set project PROJECT_ID
    Habilitar APIS:
    gcloud services enable cloudfunctions.googleapis.com run.googleapis.com artifactregistry.googleapis.com eventarc.googleapis.com cloudbuild.googleapis.com

### 3. Deploy de la función
	•	Estar parado en la carpeta con main.py y requirements.txt.
	•	Ejecutar:
    gcloud functions deploy whatsapp-bot \
  --gen2 \
  --region=us-central1 \
  --runtime=python312 \
  --entry-point=webhook \
  --trigger-http \
  --allow-unauthenticated \
  --source . \
  --set-env-vars=OPENAI_API_KEY=sk-XXXX,OPENAI_MODEL=gpt-4o-mini

### 4. Probar que funciona
	•	Healthcheck:
    curl -X GET "https://REGION-PROJECT_ID.cloudfunctions.net/whatsapp-bot"
# → ok
    *   Ping:
curl -X POST "https://REGION-PROJECT_ID.cloudfunctions.net/whatsapp-bot" -d "Body=ping"
# → <Message>pong</Message>

### 5. Conectar con Twilio
	•	En Twilio Console → WhatsApp Sandbox → “WHEN A MESSAGE COMES IN” pegar la URL pública.
	•	Guardar cambios.
	•	Enviar WhatsApp al número del Sandbox → debe responder ✅.

⸻

🛠️ Tips rápidos
	•	Usar Python 3.12 (no 3.13).
	•	Fijar httpx==0.27.2 en requirements.txt.
	•	Si el deploy cachea, usar otro nombre de función (whatsapp-bot-v2).
	•	Logs:
    gcloud functions logs read whatsapp-bot --gen2 --region=us-central1 --limit=100
    gcloud run services logs read whatsapp-bot --region=us-central1 --limit=100