from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import os, logging, requests, json, csv, io, smtplib, urllib.parse
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
            logger.info("Conexion REST a Supabase exitosa")
    except Exception as e:
        logger.error(f"Excepcion Supabase: {e}")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

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
            return response.json()["choices"]["message"]["content"].strip().replace('"', '').replace("'", "")
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
        if resp.status_code >= 200 and resp.status_code < 300:            
            return True
        return False
    except: 
        return False

def update_lead_status(lead_id, new_status="Enviado"):
    if not supabase_connected: return False
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
        url = f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}"
        resp = requests.patch(url, headers=headers, json={"estado": new_status}, timeout=5)
        if resp.status_code >= 200 and resp.status_code < 300:
            return True
        return False
    except:
        return False

def search_internal_db(query_text):
    if not supabase_connected: return []
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        url = f"{SUPABASE_URL}/rest/v1/leads?or=(nombre.ilike.*{query_text}*,rubro.ilike.*{query_text}*,distrito.ilike.*{query_text}*)&limit=100"
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json() if resp.status_code == 200 else []
    except:
        return []

def send_email_pitch(to_email, business_name, pitch_text):
    if not SMTP_PASSWORD: return False
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email
        msg["Subject"] = f"Propuesta para {business_name}"
        msg.attach(MIMEText(pitch_text, "plain"))
        server = smtplib.SMTP("://gmail.com", 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except:
        return False

def search_leads_google(keyword, location, limit=100):
    GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_KEY: return []
    url = "https://googleapis.com"
    headers = {
        "Content-Type": "application/json", 
        "X-Goog-Api-Key": GOOGLE_KEY, 
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.primaryType,places.internationalPhoneNumber"
    }
    payload = {"textQuery": f"{keyword} en {location}", "maxResultCount": min(limit, 100), "languageCode": "es"}
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
            tel = place.get("internationalPhoneNumber", "").replace(" ", "").replace("-", "")
            lead = {
                "nombre": name, 
                "rubro": keyword.capitalize(), 
                "distrito": location.title(), 
                "plan_sugerido": "STARTER",  
                "criterio_match": "Clasificacion base.", 
                "origen": "GOOGLE_MAPS", 
                "estado": "Pendiente",
                "email": "",
                "telefono": tel,
                "direccion_completa": place.get("formattedAddress", ""), 
                "pitch_automatizado": f"Hola, {name}! Ofrecemos soluciones digitales.",
                "datos_originales": {"Categoria": keyword, "Distrito": location, "Negocio": name, "Direccion": place.get("formattedAddress", "")},
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
    leads_pendientes = get_leads("Pendiente")
    rows_html = ""
    for i, lead in enumerate(leads_pendientes, 1):
        email_dest = lead.get("email", "").strip()
        tel_dest = lead.get("telefono", "").strip()
        texto_msg = urllib.parse.quote(lead.get("pitch_automatizado", ""))
        lead_id = lead.get("id")
        if email_dest:
            btn_accion = f"<form action='/api/send-email/{lead_id}' method='POST' style='margin:0;'><button type='submit' style='background:#7C3AED; color:white; padding:6px 12px; border:none; border-radius:6px; font-size:0.8rem; font-weight:bold; cursor:pointer;'>Despachar Email</button></form>"
        elif tel_dest:
            btn_accion = f"<a href='https://whatsapp.com{tel_dest}&text={texto_msg}' target='_blank' onclick='fetch(\"/api/mark-sent/{lead_id}\", {{method: \"POST\"}}); setTimeout(function(){{location.reload();}}, 1000);' style='background:#22C55E; color:white; padding:6px 12px; border-radius:6px; text-decoration:none; font-size:0.8rem; font-weight:bold; display:inline-block;'>Enviar WA</a>"
        else:
            btn_accion = "<span style='color:#64748B;'>Sin Contacto</span>"
        rows_html += f"""<tr style="border-bottom: 1px solid #1E293B;"><td style="padding:12px; text-align:center; color:#64748B;">#{i}</td><td style="padding:12px; font-weight:600; color:white;">{lead.get("nombre")}</td><td style="padding:12px; color:#94A3B8;">{lead.get("rubro")}</td><td style="padding:12px; color:#94A3B8;">{lead.get("distrito")}</td><td style="padding:12px; text-align:center;"><span style="background:#22D3EE20; color:#22D3EE; padding:4px 10px; border-radius:12px; font-size:0.8rem; font-weight:600;">{lead.get("plan_sugerido")}</span></td><td style="padding:12px; text-align:center;">{btn_accion}</td></tr>"""
    if not rows_html: rows_html = "<tr><td colspan='6' style='padding:30px; text-align:center; color:#64748B;'>No hay prospectos pendientes.</td></tr>"
    
    html_content = f"""
    <html>
    <head><title>Dashboard Leads</title></head>
    <body style="background:#0F172A; color:white; font-family:sans-serif; padding:40px;">
        <h2>Prospectos Enviados: {leads_enviados}</h2>
        <table style="width:100%; border-collapse:collapse; background:#1E293B; border-radius:8px; overflow:hidden;">
            <tr style="background:#334155; color:#CBD5E1;">
                <th style="padding:12px;">#</th><th style="padding:12px; text-align:left;">Nombre</th><th style="padding:12px; text-align:left;">Rubro</th><th style="padding:12px; text-align:left;">Distrito</th><th style="padding:12px;">Plan</th><th style="padding:12px;">Acción</th>
            </tr>
            {rows_html}
        </table>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

