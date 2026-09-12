from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from groq import Groq
import google.generativeai as genai

app = FastAPI()

# CONFIGURACIÓN DE LAS 3 KEYS
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = None
if url and key:
    try:
        from supabase import create_client
        supabase = create_client(url, key)
    except: pass

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
genai.configure(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

# GENERADOR DE PITCHES INTELIGENTE CON LÓGICA DUAL
def generate_pitch(lead_data):
    origen = lead_data.get('origen', 'autonomo')
    
    # FLUJO A: LEADS MANUALES/HISTÓRICOS (LOS 169)
    if origen == 'manual':
        return lead_data.get('pitch_validado', '[Error: Pitch manual no encontrado]')
    
    # FLUJO B: LEADS AUTÓNOMOS (NUEVOS)
    rubro = lead_data.get('rubro', 'Negocio')
    nombre = lead_data.get('nombre', 'Cliente')
    distrito = lead_data.get('distrito', 'Lima')
    plan = lead_data.get('plan_sugerido') or lead_data.get('plan', 'STARTER')
    
    # Obtener dolor desde Supabase o inferirlo
    dolor = f"Problemas operativos comunes en {rubro}."
    tema = "Eficiencia operativa"
    
    if supabase:
        try:
            res = supabase.table("content_assets").select("*").limit(1).execute()
            if res.data:
                asset = res.data[0]
                dolor = asset.get('dolor_sistemico', dolor)
                tema = asset.get('tema_central', tema)
        except: pass
    
    gancho = f"Hola {nombre}, estaba revisando negocios en {distrito} y noté que en {rubro} como el tuyo, lidiar con {dolor} suele ser el cuello de botella invisible. Es justo lo que abordamos cuando hablamos de '{tema}'."
    
    prompt = f"""Actúa como experto en ventas B2B para PYMES latinas. Eres Fernando Perez de ORASIC Lab.
Lead: {nombre}, Rubro: {rubro}, Plan: {plan}
Gancho Personalizado: {gancho}
Dolor Sistémico: {dolor}
Contexto Público: Negocio ubicado en {distrito}.

Genera pitch humano de MÁXIMO 120 palabras que:
1. USE EXACTAMENTE este gancho como primera línea.
2. Conecte el dolor con solución concreta sin jerga técnica.
3. Use tono según plan: STARTER=cercano/directo, PRO=estratégico/socio.
4. Incluya CTA de bajo riesgo: "ruta rápida de 15 min", "cero compromiso".
5. Termine con firma: "Fernando Perez - ORASIC Lab"."""

    try:
        if groq_client:
            completion = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7, max_tokens=300
            )
            return completion.choices[0].message.content.strip()
        elif GEMINI_API_KEY:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            return response.text.strip()
    except Exception as e:
        print(f"️ Error IA: {e}")
    
    return f"[Fallback] {gancho}\n\nEn ORASIC Lab resolvemos esto sin burocracia. ¿15 min esta semana? Fernando Perez"

LEADS_DATA = [
    {"id":1, "nombre":"Top Vision Barbershop", "rubro":"Barberías", "distrito":"Surco", "plan":"PRO", "origen":"manual", "pitch_validado":"Hola Top Vision, vi que te interesó nuestro contenido sobre Dependencia del Dueño..."},
    {"id":2, "nombre":"Nápoles Barber Shop", "rubro":"Barberías", "distrito":"Surco", "plan":"STARTER", "origen":"autonomo"}
]

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    leads = LEADS_DATA
    rows = ""
    for l in leads:
        pitch_text = generate_pitch(l)
        p_safe = pitch_text.replace("'", "\\'").replace("\n", "\\n")
        pl = l.get('plan_sugerido') or l.get('plan', 'STARTER')
        badge_color = "#22D3EE" if pl=="STARTER" else "#A78BFA" if pl=="MANAGER" else "#FB923C" if pl=="PRO" else "#F472B6"
        
        rows += f"""
        <tr>
            <td class="cell-name"><div class="name">{l.get('nombre','')}</div><div class="sub">{l.get('distrito','')}</div></td>
            <td>{l.get('rubro','')}</td>
            <td><span class="badge" style="background:{badge_color}20; color:{badge_color}; border:1px solid {badge_color}40">{pl}</span></td>
            <td><small style="color:#94A3B8">Origen: {l.get('origen','Manual')}</small><br><button class="btn-view" onclick="alert('{p_safe}')">️ Ver Pitch</button></td>
            <td class="cell-check"><input type='checkbox' name='ids' value='{l.get('id',0)}'></td>
        </tr>"""
    
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
            <button class="tab-btn" onclick="switchTab('manual')">📖 Manual de Uso</button>
        </div>
        <div id="dashboard" class="tab-content active">
            <div class="stats">
                <div class="card"><h3>Total Leads</h3><div class="num">{len(leads)}</div></div>
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
                <h2 style="color:var(--violet)">🤖 Motor de Inteligencia</h2>
                <p>Cada pitch se genera usando este prompt estructurado enviado a Groq/Gemini:</p>
                <pre style="background:#080A0F;padding:15px;border-radius:8px;color:var(--cyan);font-size:0.85rem;overflow-x:auto;">Actúa como experto en ventas B2B para PYMES latinas.
Lead: [Nombre], Rubro: [Rubro], Plan: [Plan]
Dolor detectado vía contenido: [Dolor_Sistémico_del_Guion]
Contexto público: [Datos_Públicos]

Genera pitch humano que:
1. Mencione explícitamente el dolor del guion como gancho
2. Conecte ese dolor con la realidad pública del negocio
3. Use tono según plan (STARTER=cercano, PRO=estratégico)
4. Máximo 150 palabras, cero jerga técnica</pre>
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
        ld = next((x for x in LEADS_DATA if str(x.get('id'))==str(i)),None)
        if ld and SMTP_PASSWORD:
            msg = MIMEMultipart()
            msg['From'] = SMTP_EMAIL; msg['To'] = SMTP_EMAIL
            msg['Subject'] = f"[TEST] {ld.get('nombre')}"
            pitch_final = generate_pitch(ld)
            msg.attach(MIMEText(pitch_final, 'plain', 'utf-8'))
            try:
                with smtplib.SMTP('smtp.gmail.com',587) as s:
                    s.starttls(); s.login(SMTP_EMAIL,SMTP_PASSWORD); s.send_message(msg)
                enviados += 1
            except: pass
    return HTMLResponse(f"<div style='background:#080A0F;color:white;padding:40px;text-align:center;font-family:sans-serif'><h2>✅ Campaña procesada</h2><p>Enviados: {enviados} a {SMTP_EMAIL}</p><a href='/' style='color:#A78BFA'>Volver al Dashboard</a></div>")

if __name__ == "__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT",8000)))
