from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import os, smtplib, random, logging, requests, time, json, csv, io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import google.generativeai as genai
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

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
            logger.info("? Conexión REST a Supabase exitosa")
        else:
            logger.error(f" Error REST Supabase: {response.status_code}")
    except Exception as e:
        logger.error(f"? Excepción conectando a Supabase: {e}")

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
        if resp.status_code in:            
            return True
        return False
    except: 
        return False

def search_leads_google(keyword, location, limit=100):
    GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_KEY: return []
    url = "https://googleapis.com"
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": GOOGLE_KEY, "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.primaryType"}
    payload = {"textQuery": f"{keyword} en {location}", "maxResultCount": min(limit, 100), "languageCode": "es"}
    PITCHES = {
        "STARTER": "¡Hola, {nombre}! Notamos que no cuentan con una plataforma web optimizada.",
        "MANAGER": "¡Hola, {nombre}! Optimiza tu negocio con nuestro sistema de reservas.",
        "PRO": "¡Hola, {nombre}! Automatiza tu atención con nuestro Chatbot IA.",
        "CUSTOM": "¡Hola, {nombre}! Desarrollamos módulos 100% a medida."
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
            prompt_clasificacion = f'Clasifica la empresa "{name}" en STARTER, MANAGER, PRO o CUSTOM. Responde solo JSON: {{"plan": "VALOR", "criterio": "RAZON"}}'
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
                    respuesta_ia = respuesta_ia.replace("`json", "").replace("`", "").strip()
                    data_json = json.loads(respuesta_ia)
                    plan_assigned = data_json.get("plan", "STARTER").upper().strip()
                    criterio_match = data_json.get("criterio", "Mapeado por IA.")
            except Exception as e:
                logger.error(f"Error clasificando con IA: {e}")
            pitch_personalizado = PITCHES.get(plan_assigned, PITCHES["STARTER"]).format(nombre=name)
            lead = {
                "nombre": name, 
                "rubro": rubro_clean, 
                "distrito": location.title(), 
                "plan_sugerido": plan_assigned,  
                "criterio_match": criterio_match, 
                "origen": "GOOGLE_MAPS", 
                "estado": "Pendiente",
                "direccion_completa": place.get("formattedAddress", ""), 
                "pitch_automatizado": pitch_personalizado,
                "datos_originales": {"Categoria": rubro_clean, "Distrito": location, "Negocio": name, "Direccion": place.get("formattedAddress", "")},
                "created_at": datetime.now().isoformat()
            }
            new_leads.append(lead)
            existing_names.add(name.lower())
        return new_leads
    except: 
        return []

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    leads_enviados = get_sent_count()
    return f"<html><body style='background:#080A0F;color:white;padding:40px;font-family:sans-serif;'><h2>?? Sistema Activo</h2><p>Leads enviados: {leads_enviados}</p><form action='/api/auto-search' method='POST'><input type='text' name='keyword' value='barberia'><input type='text' name='location' value='Lima'><button type='submit'>Buscar</button></form></body></html>"

@app.api_route("/api/auto-search", methods=["GET", "POST"])
async def auto_search(request: Request):
    if request.method == "POST":
        form = await request.form()
        keyword = form.get("keyword", "barberia")
        location = form.get("location", "Lima")
        limit = 10
    else:
        keyword = request.query_params.get("keyword", "barberia")
        location = request.query_params.get("location", "Lima")
        limit = 10
    new_leads = search_leads_google(keyword, location, limit)
    for lead in new_leads:
        insert_lead_supabase(lead)
    return {"status": "success", "encontrados": len(new_leads)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
