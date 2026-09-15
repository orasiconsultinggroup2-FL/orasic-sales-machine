from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import os, smtplib, random, logging, requests, time, json
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
        
        if response.status_code == 200:
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
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.7,
        "max_tokens": 250
    }
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,"model": "llama-3.3-70b-versatile",
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

# --- MOTOR DE BÚSQUEDA AUTOMÁTICA CON TRADUCTOR Y FILTRO INTELIGENTE ---

def search_leads_osm(keyword, location, limit=50):
    """Busca negocios en OSM con traducción automática ES->EN y filtrado por distrito"""
    
    # Diccionario de traducción transparente para ti
    translations = {
        'centros educativos': 'school', 'colegio': 'school', 'escuela': 'school', 
        'universidad': 'university', 'instituto': 'college',
        'gimnasio': 'gym', 'gimnasios': 'gym', 'fitness': 'gym',
        'barbería': 'hairdresser', 'barberias': 'hairdresser', 'peluquería': 'hairdresser',
        'restaurante': 'restaurant', 'restaurantes': 'restaurant',
        'clínica': 'clinic', 'clinicas': 'clinic', 'consultorio': 'doctors',
        'dentista': 'dentist', 'veterinaria': 'veterinary'
    }
    
    # Traducir automáticamente (si no está en lista, usa lo que escribiste)
    search_term = translations.get(keyword.lower().strip(), keyword)
    
    # Buscar en toda Lima para no perder leads, luego filtramos por distrito
    city_search = "Lima" if "lima" in location.lower() else location
    
    url = f"https://nominatim.openstreetmap.org/search?q={search_term}+{city_search}&format=json&addressdetails=1&limit={limit}"
    headers = {'User-Agent': 'OrasicSalesMachine/1.0'} 
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            new_leads = []
            
            existing_leads = get_leads("Pendiente") + get_leads("Enviado")
            existing_names = {l.get('nombre','').lower().strip() for l in existing_leads}
            
            # Preparar palabras clave del distrito para filtrar
            target_district = location.lower().replace(',', '').strip()
            district_keywords = [kw for kw in target_district.split() if len(kw) > 2]
            
            for place in data:
                raw_name = place.get('display_name', '').split(',')[0].strip()
                name = raw_name.split(' - ')[0].split('(')[0].strip() 
                
                # Evitar duplicados y nombres basura
                if name.lower() in existing_names or len(name) <= 3:
                    continue
                
                address = place.get('address', {})
                full_address = place.get('display_name', '').lower()
                
                # Filtrado inteligente: ¿La dirección contiene "Surco" o "Santiago"?
                is_match = any(kw in full_address for kw in district_keywords)
                
                if not is_match:
                    osm_district = (address.get('suburb') or address.get('city_district') or '')
                    if any(kw in osm_district.lower() for kw in district_keywords):
                        is_match = True

                if is_match:
                    district_name = (address.get('suburb') or address.get('city_district') or location).title()
                    
                    plan = "STARTER"
                    k_lower = keyword.lower()
                    if any(k in k_lower for k in ['clinica', 'hospital', 'gym', 'gimnasio', 'colegio', 'universidad', 'escuela']): 
                        plan = "PRO"
                    
                    lead = {
                        "nombre": name,
                        "rubro": keyword.capitalize(),
                        "distrito": district_name,
                        "plan_sugerido": plan,
                        "origen": "AUTO_OSM",
                        "estado": "Pendiente",
                        "email": "", 
                        "telefono": "",
                        "direccion_completa": place.get('display_name', ''),
                        "created_at": datetime.now().isoformat()
                    }
                    new_leads.append(lead)
                    existing_names.add(name.lower()) 
            
            return new_leads
        return []
    except Exception as e:
        logger.error(f"Error OSM: {e}")
        return []

@app.post("/api/auto-search")
async def auto_search(request: Request):
    form = await request.form()
    keyword = form.get("keyword", "barberia")
    location = form.get("location", "Lima")
    limit = min(int(form.get("limit", 10)), 50)
    
    time.sleep(1.1) # Respetar límites de OSM
    
    new_leads = search_leads_osm(keyword, location, limit)
    
    # Generar HTML de la tabla de vista previa
    rows_html = ""
    if new_leads:
        for i, lead in enumerate(new_leads, 1):
            rows_html += f"""
            <tr style="border-bottom: 1px solid #1E293B;">
                <td style="padding:12px; color:#A78BFA; font-weight:bold;">#{i}</td>
                <td style="padding:12px; font-weight:bold; color:white;">{lead['nombre']}</td>
                <td style="padding:12px;">{lead['rubro']}</td>
                <td style="padding:12px;">{lead['distrito']}</td>
                <td style="padding:12px;"><span style="background:#22D3EE20; color:#22D3EE; padding:4px 10px; border-radius:12px; font-size:0.75rem; font-weight:bold;">{lead['plan_sugerido']}</span></td>
                <td style="padding:12px; color:#64748b; font-size:0.8rem; max-width:300px;">{lead['direccion_completa'][:70]}...</td>
            </tr>
            """
    else:
        rows_html = "<tr><td colspan='6' style='padding:30px; text-align:center; color:#94A3B8;'>No se encontraron negocios nuevos con estos criterios en esa zona.</td></tr>"

    return HTMLResponse(f"""
    <div style='background:#080A0F;color:white;padding:40px;font-family:sans-serif;min-height:100vh;'>
        <div style='max-width:1100px; margin:0 auto;'>
            <h2 style='color:#22D3EE; margin-bottom:10px;'>🔍 Resultados: "{keyword}" en {location}</h2>
            <p style='margin-bottom:30px; color:#94A3B8;'>Se encontraron <strong>{len(new_leads)}</strong> negocios potenciales. Revisa los datos antes de importar:</p>
            
            <div style='overflow-x:auto; background:#11131A; border-radius:12px; border:1px solid #1E293B; margin-bottom:30px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);'>
                <table style='width:100%; border-collapse:collapse;'>
                    <thead>
                        <tr style='background:#1E293B; text-align:left; color:#94A3B8; font-size:0.8rem; text-transform:uppercase; letter-spacing:1px;'>
                            <th style='padding:15px;'>#</th>
                            <th style='padding:15px;'>Nombre del Negocio</th>
                            <th style='padding:15px;'>Rubro</th>
                            <th style='padding:15px;'>Distrito</th>
                            <th style='padding:15px;'>Plan Sugerido</th>
                            <th style='padding:15px;'>Ubicación Exacta</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>

            <div style='display:flex; gap:15px; justify-content:center; margin-top:40px;'>
                <a href='/' style='padding:14px 28px; background:transparent; border:1px solid #A78BFA; color:#A78BFA; border-radius:8px; text-decoration:none; font-weight:bold; transition:all 0.3s;'>Volver al Dashboard</a>
            </div>
            
            <p style='margin-top:40px; font-size:0.8rem; color:#475569; text-align:center; line-height:1.6;'>
                * OpenStreetMap proporciona ubicaciones precisas pero rara vez emails/teléfonos directos.<br>
                Para datos de contacto completos, usa el importador CSV de Claude después de validar esta lista.
            </p>
        </div>
    </div>""")

# --- NORMALIZACIÓN LINGÜÍSTICA PERFECTA ---
def normalize_lead_text(lead_data):
    rubro_raw = lead_data.get('rubro', '').strip().lower()
    distrito = lead_data.get('distrito', '').strip()
    
    corrections = {'barberíass': 'barbería', 'barberias': 'barbería', 'barberías': 'barbería',
                   'clínicaas': 'clínica', 'clinicas': 'clínica', 'clínicas': 'clínica'}
    rubro_clean = corrections.get(rubro_raw, rubro_raw)
    if rubro_clean.endswith('s') and not rubro_clean.endswith('sis'):
        rubro_clean = rubro_clean[:-1]
    
    feminine_kw = ['clínica', 'academia', 'veterinaria', 'estética', 'boutique', 'tienda', 'peluquería']
    is_feminine = any(kw in rubro_clean for kw in feminine_kw)
    
    for art in ['el ', 'la ', 'los ', 'las ']:
        if distrito.lower().startswith(art):
            distrito = distrito[len(art):].strip()
    
    lead_data['rubro_clean'] = rubro_clean
    lead_data['distrito_clean'] = distrito.title()
    lead_data['is_feminine'] = is_feminine
    return lead_data

def get_human_greeting(nombre, is_feminine):
    if is_feminine:
        return f"Hola equipo de {nombre}, estaba viendo su perfil y..."
    return f"Hola chicos de {nombre}, estaba revisando negocios en la zona y..."

def generate_pitch(lead_data):
    origen = lead_data.get('origen', 'autonomo')
    if origen == 'manual' and lead_data.get('pitch_validado'):
        return lead_data['pitch_validado']
    
    lead_data = normalize_lead_text(lead_data)
    rubro = lead_data.get('rubro_clean', 'negocio')
    nombre = lead_data.get('nombre', 'Cliente')
    distrito = lead_data.get('distrito_clean', 'Lima')
    plan = lead_data.get('plan_sugerido', 'STARTER')
    is_feminine = lead_data.get('is_feminine', False)
    
    greeting = get_human_greeting(nombre, is_feminine)
    possessive = "la tuya" if is_feminine else "el tuyo"
    hook = f"{greeting} noté que en {rubro}s como {possessive} en {distrito}, lidiar con la falta de sistemas suele ser el freno invisible."
    
    prompt = f"""Eres Fernando Perez de ORASIC Lab.
Lead: {nombre}, Rubro: {rubro}, Plan: {plan}
Gancho: {hook}
INSTRUCCIONES: Usa el gancho exacto. Tono STARTER=cercano, PRO=estratégico. Máx 100 palabras.
Termina con: "¿Te parece si agendamos 15 min esta semana? Sin compromiso. Fernando Perez - ORASIC Lab"
SOLO escribe el pitch."""

    try:
        # USAMOS LA NUEVA FUNCIÓN DIRECTA EN LUGAR DE groq_client
        pitch = call_groq_api(prompt)
        if pitch:
            return pitch
            
        # Fallback a Gemini si Groq falla
        if GEMINI_API_KEY:
            resp = genai.GenerativeModel('gemini-1.5-flash').generate_content(prompt)
            return resp.text.strip().replace('"', '')
            
    except Exception as e:
        logger.error(f"Error generando pitch: {e}")
    
    # Fallback final si todo falla
    return f"{hook} En ORASIC Lab resolvemos esto sin burocracia. ¿15 min esta semana? Fernando Perez - ORASIC Lab"

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    leads = get_leads("Pendiente")
    sent_count = get_sent_count()
    
    status_msg = ""
    if supabase_connected:
        if leads:
            status_msg = f"✅ Conectado: {len(leads)} leads cargados"
        else:
            status_msg = "⚠️ Conectado pero tabla vacía o sin estado 'Pendiente'"
    else:
        status_msg = "❌ Sin conexión a Supabase (Revisa logs)"

    rows = ""
    for idx, l in enumerate(leads, start=1):
        pitch_text = generate_pitch(l)
        p_safe = pitch_text.replace("'", "\\'").replace("\n", "\\n")
        pl = l.get('plan_sugerido', 'STARTER')
        badge_color = "#22D3EE" if pl=="STARTER" else "#A78BFA" if pl=="MANAGER" else "#FB923C" if pl=="PRO" else "#F472B6"
        
        rows += f"""
        <tr>
            <td style="font-weight:bold; color:var(--violet); width:50px; text-align:center;">#{idx}</td>
            <td class="cell-name"><div class="name">{l.get('nombre','')}</div><div class="sub">{l.get('distrito','')}</div></td>
            <td>{l.get('rubro','')}</td>
            <td><span class="badge" style="background:{badge_color}20; color:{badge_color}; border:1px solid {badge_color}40">{pl}</span></td>
            <td><small style="color:#94A3B8">Origen: {l.get('origen','').upper()}</small><br><button class="btn-view" onclick="alert('{p_safe}')">👁️ Ver Pitch</button></td>
            <td class="cell-check"><input type='checkbox' name='ids' value='{l.get('id','')}'></td>
        </tr>"""
    
    total_leads = len(leads)
    pending_leads = total_leads
    status_html = f"<div style='text-align:center; padding:20px; background:#11131A; border-radius:8px; margin-bottom:20px; color:{'#22D3EE' if '✅' in status_msg else '#F472B6'}'>{status_msg}</div>"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>ORASIC Sales Machine</title>
    <style>
        :root {{ --bg: #080A0F; --card: #11131A; --text: #E2E8F0; --muted: #94A3B8; --border: #1E293B; 
                --violet: #A78BFA; --cyan: #22D3EE; --pink: #F472B6; --orange: #FB923C; }}
        body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; min-height: 100vh; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 40px; }}
        .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 30px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }}
        .logo-area {{ display: flex; align-items: center; gap: 15px; }}
        .logo-icon {{ width: 45px; height: 45px; background: linear-gradient(135deg, var(--violet), var(--cyan)); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-weight: 900; color: white; font-size: 1.5rem; box-shadow: 0 0 15px rgba(167,139,250,0.4); }}
        .brand h1 {{ margin: 0; font-size: 1.4rem; letter-spacing: -0.5px; }}
        .brand span {{ color: var(--violet); }}
        .brand small {{ color: var(--muted); font-size: 0.75rem; display: block; margin-top: 2px; }}
        .tabs {{ display: flex; gap: 10px; margin-bottom: 30px; }}
        .tab-btn {{ background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: all 0.3s; }}
        .tab-btn.active {{ background: var(--violet); color: white; border-color: var(--violet); box-shadow: 0 0 15px rgba(167,139,250,0.3); }}
        .tab-content {{ display: none; animation: fadeIn 0.4s ease; }}
        .tab-content.active {{ display: block; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; position: relative; overflow: hidden; }}
        .card::before {{ content:''; position:absolute; top:0; left:0; width:4px; height:100%; background:var(--violet); }}
        .card h3 {{ margin: 0 0 10px 0; font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }}
        .card .num {{ font-size: 2.2rem; font-weight: bold; color: white; }}
        table {{ width: 100%; border-collapse: separate; border-spacing: 0 10px; }}
        th {{ text-align: left; padding: 15px; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; }}
        td {{ background: var(--card); padding: 15px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); vertical-align: middle; }}
        td:first-child {{ border-left: 1px solid var(--border); border-radius: 8px 0 0 8px; }}
        td:last-child {{ border-right: 1px solid var(--border); border-radius: 0 8px 8px 0; text-align: center; }}
        .cell-name .name {{ font-weight: 600; color: white; }}
        .cell-name .sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 4px; }}
        .badge {{ padding: 4px 10px; border-radius: 20px; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.5px; }}
        .btn-view {{ background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 6px 12px; border-radius: 6px; cursor: pointer; transition: all 0.2s; font-size: 0.8rem; }}
        .btn-view:hover {{ border-color: var(--cyan); color: var(--cyan); box-shadow: 0 0 10px rgba(34,211,238,0.2); }}
        input[type="checkbox"] {{ width: 18px; height: 18px; accent-color: var(--violet); cursor: pointer; }}
        .actions {{ margin-top: 30px; text-align: right; }}
        .btn-disparar {{ background: linear-gradient(90deg, var(--violet), var(--pink)); color: white; border: none; padding: 14px 30px; border-radius: 8px; font-weight: bold; font-size: 1rem; cursor: pointer; box-shadow: 0 4px 20px rgba(167, 139, 250, 0.4); transition: transform 0.2s; }}
        .btn-disparar:hover {{ transform: translateY(-2px); box-shadow: 0 6px 25px rgba(167, 139, 250, 0.6); }}
        @keyframes fadeIn {{ from {{ opacity:0; transform:translateY(10px); }} to {{ opacity:1; transform:translateY(0); }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo-area">
                <div class="logo-icon">O</div>
                <div class="brand">
                    <h1>ORASIC <span>Sales Machine</span></h1>
                    <small>by NIROMA Labs • v1.2</small>
                </div>
            </div>
        </div>
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('dashboard')"> Dashboard de Leads</button>
            <button class="tab-btn" onclick="switchTab('manual')"> Manual de Uso</button>
        </div>
        <div id="dashboard" class="tab-content active">
            {status_html}
            <div class="stats">
                <div class="card"><h3>Total Leads Reales</h3><div class="num">{total_leads}</div></div>
                <div class="card" style="--violet:var(--cyan)"><h3>Pendientes</h3><div class="num" style="color:var(--cyan)">{pending_leads}</div></div>
                <div class="card" style="--violet:var(--muted)"><h3>Enviados</h3><div class="num" style="color:var(--muted)">{sent_count}</div></div>
            </div>
            
            <!-- MOTOR DE PROSPECCIÓN AUTOMÁTICA -->
            <div class="card" style="margin-bottom:30px; border:1px solid var(--violet);">
                <h3 style="color:var(--violet); margin-bottom:15px;"> Motor de Prospección Automática (OpenStreetMap)</h3>
                <form action="/api/auto-search" method="post" style="display:flex; gap:10px; flex-wrap:wrap; align-items:end;">
                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:var(--muted); display:block; margin-bottom:5px;">Rubro / Keyword</label>
                        <input type="text" name="keyword" value="Barbería" required 
                               style="width:100%; padding:10px; background:var(--bg); border:1px solid var(--border); color:white; border-radius:6px;">
                    </div>
                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:var(--muted); display:block; margin-bottom:5px;">Ubicación</label>
                        <input type="text" name="location" value="Santiago de Surco, Lima" required 
                               style="width:100%; padding:10px; background:var(--bg); border:1px solid var(--border); color:white; border-radius:6px;">
                    </div>
                    <div style="width:100px;">
                        <label style="font-size:0.8rem; color:var(--muted); display:block; margin-bottom:5px;">Cantidad</label>
                        <input type="number" name="limit" value="10" min="1" max="50" 
                               style="width:100%; padding:10px; background:var(--bg); border:1px solid var(--border); color:white; border-radius:6px;">
                    </div>
                    <button type="submit" class="btn-disparar" style="padding:10px 20px; font-size:0.9rem;">
                        🔎 Buscar Leads
                    </button>
                </form>
                <p style="font-size:0.75rem; color:var(--muted); margin-top:10px;">
                    * Fuente: OpenStreetMap (Gratis). Datos básicos. Para emails/teléfonos usa el importador CSV de Claude.
                </p>
            </div>

            <form action="/disparar" method="post">
                <table>
                    <thead><tr><th>#</th><th>Negocio / Ubicación</th><th>Rubro</th><th>Plan</th><th>Pitch</th><th>Enviar</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
                <div class="actions"><button type="submit" class="btn-disparar"> DISPARAR SELECCIONADOS</button></div>
            </form>
        </div>
        <div id="manual" class="tab-content">
            <div class="manual-section" style="background:var(--card);padding:30px;border-radius:12px;margin-bottom:20px;">
                <h2 style="color:var(--violet)"> Motor de Inteligencia Humana</h2>
                <p>Cada pitch autónomo se genera usando este prompt estructurado enviado a Groq/Gemini:</p>
                <pre style="background:#080A0F;padding:15px;border-radius:8px;color:var(--cyan);font-size:0.85rem;overflow-x:auto;">Eres Fernando Perez de ORASIC Lab.
Lead: [Nombre], Rubro: [Rubro], Plan: [Plan]
Dolor detectado: [Dolor_Sistémico_de_tus_Guiones]
Saludo personalizado: [Detectado por género del negocio]

Genera pitch humano que:
1. Use saludo cercano y natural (no corporativo)
2. Conecte dolor con realidad local del negocio
3. Tono STARTER=cercano / PRO=estratégico
4. Máx 100 palabras, cero jerga
5. CTA: "15 min sin compromiso"</pre>
            </div>
        </div>
    </div>
    <script>
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }}
    </script>
</body>
</html>"""

@app.post("/disparar")
async def disparar(request: Request):
    form = await request.form()
    ids = form.getlist("ids")
    enviados = 0
    
    if supabase_connected and ids:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        
        for lead_id in ids:
            try:
                update_url = f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}"
                payload = {"estado": "Enviado"}
                resp = requests.patch(update_url, headers=headers, json=payload, timeout=5)
                if resp.status_code in [200, 204]:
                    enviados += 1
            except Exception as e:
                logger.error(f"Error updating lead {lead_id}: {e}")
            
    return HTMLResponse(f"""
    <div style='background:#080A0F;color:white;padding:40px;text-align:center;font-family:sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;'>
        <h2 style='color:#22D3EE'>✅ Campaña procesada</h2>
        <p style='font-size:1.2rem;margin:20px 0'>Enviados: <strong>{enviados}</strong> leads</p>
        <p style='color:#94A3B8'>Los estados han sido actualizados en Supabase.</p>
        <a href='/' style='margin-top:30px;color:#A78BFA;text-decoration:none;border:1px solid #A78BFA;padding:10px 20px;border-radius:8px;'>Volver al Dashboard</a>
    </div>""")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))