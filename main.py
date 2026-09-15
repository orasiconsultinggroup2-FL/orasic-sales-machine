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

# CONFIGURACIÓN SUPABASE VIA REST API DIRECTA (INTACTA)
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
        
        if response.status_code in:
            supabase_connected = True
            logger.info(f"✅ Conexión REST a Supabase exitosa: {SUPABASE_URL}")
        else:
            logger.error(f" Error REST Supabase: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        logger.error(f"❌ Excepción conectando a Supabase: {e}")
else:
    logger.warning("⚠️ Faltan variables SUPABASE_URL o SUPABASE_KEY")

# CONFIGURACIÓN GROQ SIN LIBRERÍA EXTERNA (FIX RAILWAY CRASH)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def call_groq_api(prompt_text):
    """Llama a Groq via requests nativos para evitar conflicto httpx en Railway"""
    if not GROQ_API_KEY: 
        logger.warning("⚠️ GROQ_API_KEY no configurada")
        return None
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama3-8b-8192",
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.7,
        "max_tokens": 250
    }
    
    try:
        response = requests.post(
            "https://groq.com",
            headers=headers,
            json=payload,
            timeout=15
        )
        
        if response.status_code == 200:
            result = response.json()["choices"][0]["message"]["content"].strip()
            return result.replace('"', '').replace("'", "")
        else:
            logger.error(f"❌ Error Groq API: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f" Excepción Groq: {e}")
        return None

# Configurar Gemini si está disponible
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

# --- FUNCIONES DE DATOS ---

def get_leads(status="Pendiente"):
    """Obtiene leads por estado usando REST API directa"""
    if not supabase_connected:
        return []
    
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        url = f"{SUPABASE_URL}/rest/v1/leads?estado=eq.{status}&limit=200"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        logger.error(f"Error obteniendo leads ({status}): {e}")
        return []

def get_sent_count():
    """Obtiene el conteo real de leads enviados"""
    if not supabase_connected:
        return 0
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Prefer": "count=exact"
        }
        url = f"{SUPABASE_URL}/rest/v1/leads?estado=eq.Enviado&select=id"
        resp = requests.get(url, headers=headers, timeout=5)
        range_header = resp.headers.get('Content-Range', '')
        return int(range_header.split('/')[-1]) if '/' in range_header else 0
    except:
        return 0

def insert_lead_supabase(lead):
    """Inserta un nuevo lead directamente en Supabase via REST API"""
    if not supabase_connected:
        return False
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        url = f"{SUPABASE_URL}/rest/v1/leads"
        resp = requests.post(url, headers=headers, json=lead, timeout=5)
        return resp.status_code in [200, 201, 204]
    except Exception as e:
        logger.error(f"Error insertando lead en Supabase: {e}")
        return False

# --- MOTOR DE BÚSQUEDA AUTOMÁTICA CON TRADUCTOR Y FILTRO INTELIGENTE ---

def search_leads_google(keyword, location, limit=100):
    """Busca negocios con Google Places API (New), asigna Plan v4.1, límite de 100 y Pitches Abiertos"""
    GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_KEY:
        logger.warning("⚠️ GOOGLE_MAPS_API_KEY no configurada en Railway")
        return []

    loc_clean = location.lower().strip()
    is_surco = "surco" in loc_clean
    target_district_name = "Santiago de Surco" if is_surco else location.title()

    url = "https://googleapis.com"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.addressComponents,places.primaryType"
    }
    
    payload = {
        "textQuery": f"{keyword} en {location}",
        "maxResultCount": min(limit, 100),
        "languageCode": "es"
    }

    PITCHES = {
        "STARTER": "¡Hola, {nombre}! Notamos que no cuentan con una plataforma web optimizada para recibir clientes en su zona. Te ofrecemos presencia digital llave en mano por solo S/599 setup + S/99/mes.",
        "MANAGER": "¡Hola, {nombre}! Optimiza tu negocio con nuestro sistema de reservas con calendario visual en Supabase por S/649 setup + S/149/mes.",
        "PRO": "¡Hola, {nombre}! Automatiza tu atención con nuestro Chatbot IA para WhatsApp Business API activo 24/7 por S/699 setup + S/199/mes.",
        "CUSTOM": "¡Hola, {nombre}! Desarrollamos módulos 100% a medida con integraciones ERP avanzadas. Cotización previa auditoría."
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code != 200:
            logger.error(f"❌ Error Google Maps API: {resp.status_code}")
            return []
            
        data = resp.json()
        places = data.get("places", [])
        new_leads = []

        existing_leads = get_leads("Pendiente") + get_leads("Enviado")
        existing_names = {l.get('nombre','').lower().strip() for l in existing_leads}

        for place in places:
            name = place.get("displayName", {}).get("text", "").strip()
            if not name or name.lower() in existing_names:
                continue

            # FILTRADO GEOGRÁFICO SUAVIZADO COMPATIBLE
            in_district = True

            if in_district:
                # 🧠 MOTOR DE CLASIFICACIÓN ABIERTO MEDIANTE IA
                rubro_clean = keyword.capitalize()
                tipo_google = place.get('primaryType', 'Desconocido')
                
                prompt_clasificacion = f'Clasifica la empresa "{name}" (Rubro: {rubro_clean}, GoogleType: {tipo_google}) en STARTER, MANAGER, PRO o CUSTOM. Responde solo JSON sin markdown: {{"plan": "VALOR", "criterio": "RAZON"}}'
                plan_asignado = "STARTER"
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
                        plan_asignado = data_json.get("plan", "STARTER").upper().strip()
                        criterio_match = data_json.get("criterio", "Mapeado por IA.")
                except:
                    if any(k in rubro_clean.lower() for k in ["barber", "peluquer", "salon", "dentista", "cancha", "estetica", "restaurante", "chifa"]):
                        plan_asignado = "MANAGER"

                pitch_personalizado = PITCHES.get(plan_asignado, PITCHES["STARTER"]).format(nombre=name)

                lead = {
                    "nombre": name,
                    "rubro": rubro_clean,
                    "distrito": target_district_name,
                    "plan_sugerido": plan_asignado,  
                    "criterio_match": criterio_match,
                    "origen": "GOOGLE_MAPS",
                    "estado": "Pendiente",
                    "email": "", 
                    "telefono": "",
                    "direccion_completa": place.get("formattedAddress", ""),
                    "pitch_automatizado": pitch_personalizado,
                    "datos_originales": {"Categoria": rubro_clean, "Distrito": target_district_name, "Negocio": name, "Direccion": place.get("formattedAddress", "")},
                    "created_at": datetime.now().isoformat()
                }
                new_leads.append(lead)
                existing_names.add(name.lower())

        return new_leads
    except Exception as e:
