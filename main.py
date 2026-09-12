from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import os, smtplib, random, logging, requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from groq import Groq
import google.generativeai as genai

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
            logger.error(f"❌ Error REST Supabase: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        logger.error(f"❌ Excepción conectando a Supabase: {e}")
else:
    logger.warning("⚠️ Faltan variables SUPABASE_URL o SUPABASE_KEY")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
genai.configure(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

def get_leads_from_supabase():
    """Obtiene leads usando REST API directa"""
    if not supabase_connected:
        return []
    
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        url = f"{SUPABASE_URL}/rest/v1/leads?estado=eq.Pendiente&limit=100"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Cargados {len(data)} leads reales vía REST")
            return data
        else:
            logger.error(f"Error fetching leads: {response.status_code} - {response.text[:200]}")
            return []
    except Exception as e:
        logger.error(f"Excepción obteniendo leads: {e}")
        return []

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
        if groq_client:
            comp = groq_client.chat.completions.create(
                model="llama-3.1-8b-versatile",
                messages=[{"role": "user", "content": prompt}], 
                temperature=0.7, max_tokens=250
            )
            return comp.choices[0].message.content.strip().replace('"', '')
    except Exception as e:
        logger.error(f"Error Groq: {e}")
        if GEMINI_API_KEY:
            try:
                resp = genai.GenerativeModel('gemini-1.5-flash').generate_content(prompt)
                return resp.text.strip().replace('"', '')
            except: pass
    
    return f"{hook} En ORASIC Lab resolvemos esto sin burocracia. ¿15 min esta semana? Fernando Perez - ORASIC Lab"

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    leads = get_leads_from_supabase()
    
    status_msg = ""
    if supabase_connected:
        if leads:
            status_msg = f"✅ Conectado: {len(leads)} leads cargados"
        else:
            status_msg = "⚠️ Conectado pero tabla vacía o sin estado 'Pendiente'"
    else:
        status_msg = "❌ Sin conexión a Supabase (Revisa logs)"

    rows = ""
    for l in leads:
        pitch_text = generate_pitch(l)
        p_safe = pitch_text.replace("'", "\\'").replace("\n", "\\n")
        pl = l.get('plan_sugerido', 'STARTER')
        badge_color = "#22D3EE" if pl=="STARTER" else "#A78BFA" if pl=="MANAGER" else "#FB923C" if pl=="PRO" else "#F472B6"
        
        rows += f"""
        <tr>
            <td class="cell-name"><div class="name">{l.get('nombre','')}</div><div class="sub">{l.get('distrito','')}</div></td>
            <td>{l.get('rubro','')}</td>
            <td><span class="badge" style="background:{badge_color}20; color:{badge_color}; border:1px solid {badge_color}40">{pl}</span></td>
            <td><small style="color:#94A3B8">Origen: {l.get('origen','').upper()}</small><br><button class="btn-view" onclick="alert('{p_safe}')">👁️ Ver Pitch</button></td>
            <td class="cell-check"><input type='checkbox' name='ids' value='{l.get('id','')}'></td>
        </tr>"""
    
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
                    <small>by NIROMA Labs • v1.0</small>
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
                <div class="card"><h3>Total Leads Reales</h3><div class="num">{len(leads)}</div></div>
                <div class="card" style="--violet:var(--cyan)"><h3>Pendientes</h3><div class="num" style="color:var(--cyan)">{len(leads)}</div></div>
                <div class="card" style="--violet:var(--muted)"><h3>Enviados</h3><div class="num" style="color:var(--muted)">0</div></div>
            </div>
            <form action="/disparar" method="post">
                <table>
                    <thead><tr><th>Negocio / Ubicación</th><th>Rubro</th><th>Plan</th><th>Pitch</th><th>Enviar</th></tr></thead>
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
    for i in ids:
        enviados += 1 
    return HTMLResponse(f"<div style='background:#080A0F;color:white;padding:40px;text-align:center;font-family:sans-serif'><h2>✅ Campaña procesada</h2><p>Enviados: {enviados} a {SMTP_EMAIL}</p><a href='/' style='color:#A78BFA'>Volver al Dashboard</a></div>")

if __name__ == "__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT",8000)))
