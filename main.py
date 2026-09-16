from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import os, smtplib, random, logging, requests, time, json, csv, io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import google.generativeai as genai

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CONFIGURACIÓN SUPABASE VIA REST API DIRECTA
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase_connected = False

if SUPABASE_URL and SUPABASE_KEY:
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        test_url = f"{SUPABASE_URL}/rest/v1/leads?select=id&limit=1"
        response = requests.get(test_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            supabase_connected = True
            logger.info(f"✅ Conexión REST a Supabase exitosa: {SUPABASE_URL}")
        else:
            logger.error(f" Error REST Supabase: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        logger.error(f"❌ Excepción conectando a Supabase: {e}")
else:
    logger.warning("⚠️ Faltan variables SUPABASE_URL o SUPABASE_KEY")

# CONFIGURACIÓN GROQ Y GEMINI
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def call_groq_api(prompt_text):
    if not GROQ_API_KEY: return None
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-8b-8192",
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.7, "max_tokens": 250
    }
    try:
        response = requests.post("https://groq.com", headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip().replace('"', '').replace("'", "")
    except: 
        return None

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- FUNCIONES DE DATOS ---

def get_leads(status="Pendiente"):
    if not supabase_connected: return []
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        url = f"{SUPABASE_URL}/rest/v1/leads?estado=eq.{status}&limit=200"
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json() if resp.status_code == 200 else []
    except: 
        return []

def get_sent_count():
    if not supabase_connected: return 0
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Prefer": "count=exact"}
        resp = requests.get(f"{SUPABASE_URL}/rest/v1/leads?estado=eq.Enviado&select=id", headers=headers, timeout=5)
        return int(resp.headers.get('Content-Range', '').split('/')[-1]) if '/' in resp.headers.get('Content-Range', '') else 0
    except: 
        return 0

def insert_lead_supabase(lead):
    if not supabase_connected: return False
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/leads", headers=headers, json=lead, timeout=5)
        if resp.status_code == 200 or resp.status_code == 201 or resp.status_code == 204:
            return True
        return False
    except: 
        return False

# --- MOTOR DE BÚSQUEDA AUTOMÁTICAAbierto MEDIANTE IA ---

def search_leads_google(keyword, location, limit=100):
    GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_KEY: return []
    
    url = "https://googleapis.com"
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": GOOGLE_KEY, "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.primaryType"}
    payload = {"textQuery": f"{keyword} en {location}", "maxResultCount": min(limit, 100), "languageCode": "es"}

    PITCHES = {
        "STARTER": "¡Hola, {nombre}! Notamos que no cuentan con una plataforma web optimizada para recibir clientes en su zona. Te ofrecemos presencia digital llave en mano por solo S/599 setup + S/99/mes.",
        "MANAGER": "¡Hola, {nombre}! Optimiza tu negocio con nuestro sistema de reservas con calendario visual en Supabase por S/649 setup + S/149/mes.",
        "PRO": "¡Hola, {nombre}! Automatiza tu atención con nuestro Chatbot IA para WhatsApp Business API activo 24/7 por S/699 setup + S/199/mes.",
        "CUSTOM": "¡Hola, {nombre}! Desarrollamos módulos 100% a medida con integraciones ERP avanzadas. Cotización previa auditoría."
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code != 200: return []
        places = resp.json().get("places", [])
        new_leads = []
        
        existing_leads = get_leads("Pendiente") + get_leads("Enviado")
        existing_names = {l.get('nombre','').lower().strip() for l in existing_leads}

        for place in places:
            name = place.get("displayName", {}).get("text", "").strip()
            if not name or name.lower() in existing_names: continue

            rubro_clean = keyword.capitalize()
            tipo_google = place.get('primaryType', 'Desconocido')
            
            prompt_clasificacion = f'Clasifica la empresa "{name}" (Rubro: {rubro_clean}, GoogleType: {tipo_google}) en STARTER, MANAGER, PRO o CUSTOM. Responde solo JSON sin markdown: {{"plan": "VALOR", "criterio": "RAZON"}}'
            plan_assigned = "STARTER"
            criterio_match = "Clasificación base."

          try:
                respuesta_ia = None
                if GEMINI_API_KEY:
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    res = model.generate_content(prompt_clasificacion)
                    respuesta_ia = res.text.strip()
                elif GROQ_API_KEY:
                    respuesta_ia = call_groq_api(prompt_clasificacion)

                if respuesta_ia:
                    respuesta_ia = respuesta_ia.replace("```json", "").replace("```", "").strip()
                    data_json = json.loads(respuesta_ia)
                    plan_assigned = data_json.get("plan", "STARTER").upper().strip()
                    criterio_match = data_json.get("criterio", "Mapeado por IA.")
            except Exception as e:
                logger.error(f"Error clasificando con IA: {e}")
                # Fallback manual si la IA falla
                if any(k in rubro_clean.lower() for k in ["barber", "peluquer", "salon", "dentista", "cancha", "estetica", "restaurante", "chifa"]):
                    plan_assigned = "MANAGER"

            pitch_personalizado = PITCHES.get(plan_assigned, PITCHES["STARTER"]).format(nombre=name)

            lead = {
                "nombre": name, "rubro": rubro_clean, "distrito": location.title(), "plan_sugerido": plan_assigned,  
                "criterio_match": criterion_match, "origen": "GOOGLE_MAPS", "estado": "Pendiente",
                "direccion_completa": place.get("formattedAddress", ""), "pitch_automatizado": pitch_personalizado,
                "datos_originales": {"Categoria": rubro_clean, "Distrito": location, "Negocio": name, "Direccion": place.get("formattedAddress", "")},
                "created_at": datetime.now().isoformat()
            }
            new_leads.append(lead)
            existing_names.add(name.lower())
        return new_leads
    except: 
        return []

@app.post("/api/auto-search")
async def auto_search(request: Request):
    form = await request.form()
    keyword = form.get("keyword", "barberia")
    location = form.get("location", "Lima")
    limit = min(int(form.get("limit", 10)), 100)
    
    new_leads = search_leads_google(keyword, location, limit)
    rows_html = ""
    for i, lead in enumerate(new_leads, 1):
        insert_lead_supabase(lead)
        rows_html += f'<tr style="border-bottom: 1px solid #1E293B;"><td style="padding:12px; text-align:center;">#{i}</td><td style="padding:12px; font-weight:bold; color:white;">{lead["nombre"]}</td><td style="padding:12px;">{lead["rubro"]}</td><td style="padding:12px;">{lead["distrito"]}</td><td style="padding:12px; text-align:center;"><span style="background:#22D3EE20; color:#22D3EE; padding:4px 10px; border-radius:12px;">{lead["plan_sugerido"]}</span></td><td style="padding:12px; color:#94A3B8; font-size:0.8rem;"><em>{lead["criterio_match"]}</em></td></tr>'
    
    if not new_leads: rows_html = "<tr><td colspan='6' style='padding:30px; text-align:center; color:#94A3B8;'>No se encontraron nuevos registros.</td></tr>"
    return HTMLResponse(f"<div style='background:#080A0F;color:white;padding:40px;font-family:sans-serif;min-height:100vh;'><div style='max-width:1100px; margin:0 auto;'><h2>🔍 Resultados Importados</h2><table style='width:100%; border-collapse:collapse;'><tr style='background:#1E293B; color:#94A3B8;'><th>#</th><th>Nombre</th><th>Rubro</th><th>Ubicación</th><th>Plan</th><th>Criterio Match</th></tr>{rows_html}</table><br><a href='/' style='color:#A78BFA;text-decoration:none;'>Volver al Dashboard</a></div></div>")

@app.post("/api/import-personal-csv")
async def import_personal_csv(request: Request):
    form = await request.form()
    raw_csv = form.get("personal_csv_data", "").strip()
    if not raw_csv: return HTMLResponse("Caja vacía.")
    
    try:
        f = io.StringIO(raw_csv)
        reader = csv.DictReader(f)
        imported_count = 0
        for row in reader:
            nombre = row.get("Negocio", "").strip()
            if not nombre: continue
            rubro = row.get("Categoria", "").strip()
            distrito = row.get("Distrito", "").strip()
            direccion = row.get("Direccion", "").strip()
            
            plan_assigned = "STARTER"
