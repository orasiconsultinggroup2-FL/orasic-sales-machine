from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import os, logging, requests, json, csv, io, smtplib, urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import google.generativeai as genai
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- CONFIGURACIÓN ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase_connected = False

if SUPABASE_URL and SUPABASE_KEY:
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
        test_url = f"{SUPABASE_URL}/rest/v1/leads?select=id&limit=1"
        response = requests.get(test_url, headers=headers, timeout=5)
        if response.status_code == 200:
            supabase_connected = True
            logger.info("✅ Conexión REST a Supabase exitosa")
    except Exception as e:
        logger.error(f"❌ Excepción Supabase: {e}")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

# --- LISTAS PREDEFINIDAS PARA DROPDOWNS ---

RUBROS_NEGOCIOS = [
    "Abogados", "Academias", "Agencias de Viajes", "Almacenes", "Arquitectos", 
    "Asesorías", "Automotriz", "Bancos", "Barberías", "Bares", "Bibliotecas", 
    "Bodegas", "Boutiques", "Cafeterías", "Calzados", "Canchas Deportivas", 
    "Carnicerías", "Centros Comerciales", "Cerámicas", "Clínicas", "Colegios", 
    "Consultoras", "Constructoras", "Contadores", "Dentistas", "Discotecas", 
    "Estéticas", "Farmacias", "Ferreterías", "Fitness", "Florerías", 
    "Gimnasios", "Hoteles", "Imprentas", "Jardinería", "Joyeros", "Laboratorios", 
    "Lavanderías", "Librerías", "Mascotas", "Mecánicos", "Medicinas", 
    "Mueblerías", "Ópticas", "Panaderías", "Peluquerías", "Pet Shops", 
    "Polideportivos", "Restaurantes", "Salones de Eventos", "Supermercados", 
    "Talleres", "Tiendas de Ropa", "Veterinarias", "Zapaterías", "Otro"
]

DISTRITOS_LIMA = [
    "Ancón", "Ate", "Barranco", "Breña", "Carabayllo", "Chaclacayo", 
    "Chorrillos", "Cieneguilla", "Comas", "El Agustino", "Independencia", 
    "Jesús María", "La Molina", "La Victoria", "Lima", "Lince", 
    "Los Olivos", "Lurigancho", "Lurín", "Magdalena del Mar", "Miraflores", 
    "Pachacámac", "Pucusana", "Pueblo Libre", "Puente Piedra", "Punta Hermosa", 
    "Punta Negra", "Rímac", "San Bartolo", "San Borja", "San Isidro", 
    "San Juan de Lurigancho", "San Juan de Miraflores", "San Luis", 
    "San Martín de Porres", "San Miguel", "Santa Anita", "Santa María del Mar", 
    "Santa Rosa", "Santiago de Surco", "Surquillo", "Villa El Salvador", 
    "Villa María del Triunfo", "Otro"
]

# --- FUNCIONES AUXILIARES ---

def call_groq_api(prompt_text):
    if not GROQ_API_KEY: return None
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "llama3-8b-8192", "messages": [{"role": "user", "content": prompt_text}], "temperature": 0.7, "max_tokens": 250}
    try:
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
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
        range_header = resp.headers.get('Content-Range', '')
        return int(range_header.split('/')[-1]) if '/' in range_header else 0
    except: 
        return 0

def insert_lead_supabase(lead):
    if not supabase_connected: return False
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/leads", headers=headers, json=lead, timeout=5)
        return resp.status_code >= 200 and resp.status_code < 300
    except: 
        return False

def update_lead_status(lead_id, new_status="Enviado"):
    if not supabase_connected or not lead_id: return False
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
        url = f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}"
        resp = requests.patch(url, headers=headers, json={"estado": new_status}, timeout=5)
        return resp.status_code >= 200 and resp.status_code < 300
    except:
        return False

def send_email_pitch(to_email, business_name, pitch_text):
    if not SMTP_PASSWORD: 
        logger.warning("⚠️ SMTP Password no configurada")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email
        msg["Subject"] = f"Propuesta para {business_name}"
        msg.attach(MIMEText(pitch_text, "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Error enviando email: {e}")
        return False

# --- MOTOR DE BÚSQUEDA UNIVERSAL GOOGLE MAPS ---

def search_leads_google(keyword, location, limit=100):
    GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_KEY: return []
    
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json", 
        "X-Goog-Api-Key": GOOGLE_KEY, 
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.primaryType,places.internationalPhoneNumber"
    }
    payload = {"textQuery": f"{keyword} en {location}", "maxResultCount": min(limit, 100), "languageCode": "es"}
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code != 200: 
            logger.error(f"Error Google Maps: {resp.status_code}")
            return []
            
        places = resp.json().get("places", [])
        new_leads = []
        existing_leads = get_leads("Pendiente") + get_leads("Enviado")
        existing_names = {l.get('nombre','').lower().strip() for l in existing_leads}
        
        for place in places:
            name = place.get("displayName", {}).get("text", "").strip()
            if not name or name.lower() in existing_names: continue
            
            tel = place.get("internationalPhoneNumber", "").replace(" ", "").replace("-", "")
            pitch_simple = f"Hola equipo de {name}, soy Fernando de ORASIC Lab. Vi su negocio de {keyword} en {location} y tengo una propuesta digital para potenciar sus ventas."

            lead = {
                "nombre": name, 
                "rubro": keyword.capitalize(), 
                "distrito": location.title(), 
                "plan_sugerido": "STARTER",  
                "criterio_match": "Búsqueda Universal Google Maps", 
                "origen": "GOOGLE_MAPS", 
                "estado": "Pendiente",
                "email": "",
                "telefono": tel,
                "direccion_completa": place.get("formattedAddress", ""), 
                "pitch_automatizado": pitch_simple,
                "datos_originales": {"Categoria": keyword, "Distrito": location, "Negocio": name, "Direccion": place.get("formattedAddress", "")},
                "created_at": datetime.now().isoformat()
            }
            new_leads.append(lead)
            existing_names.add(name.lower())
        return new_leads
    except Exception as e:
        logger.error(f"Error en search_leads_google: {e}")
        return []

# --- RUTAS DE LA API ---

@app.post("/api/auto-search")
async def auto_search(request: Request):
    form = await request.form()
    keyword = form.get("keyword", "")
    location = form.get("location", "")
    limit = min(int(form.get("limit", 10)), 100)
    
    # Si selecciona "Otro", usa el texto libre, sino usa el seleccionado
    if keyword == "Otro":
        keyword = form.get("keyword_other", "").strip()
    if location == "Otro":
        location = form.get("location_other", "").strip()

    if not keyword or not location:
        return JSONResponse({"error": "Debes ingresar un rubro y un distrito"}, status_code=400)

    new_leads = search_leads_google(keyword, location, limit)
    
    count_inserted = 0
    for lead in new_leads:
        if insert_lead_supabase(lead):
            count_inserted += 1
            
    return JSONResponse({
        "mensaje": f"Búsqueda completada. {len(new_leads)} encontrados, {count_inserted} guardados.", 
        "leads": new_leads
    })

@app.post("/api/mark-sent/{lead_id}")
async def mark_sent(lead_id: str):
    if update_lead_status(lead_id, "Enviado"):
        return JSONResponse({"status": "success"})
    return JSONResponse({"status": "error"}, status_code=500)

@app.post("/api/send-email/{lead_id}")
async def send_email_route(lead_id: str):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}"
    resp = requests.get(url, headers=headers, timeout=5)
    
    if resp.status_code != 200 or not resp.json():
        return JSONResponse({"status": "error", "msg": "Lead no encontrado"}, status_code=404)
        
    lead = resp.json()[0]
    email_dest = lead.get("email", "").strip()
    
    if not email_dest:
        return JSONResponse({"status": "error", "msg": "Lead sin email"}, status_code=400)
        
    success = send_email_pitch(email_dest, lead.get("nombre"), lead.get("pitch_automatizado", ""))
    
    if success:
        update_lead_status(lead_id, "Enviado")
        return JSONResponse({"status": "success"})
    else:
        return JSONResponse({"status": "error", "msg": "Fallo al enviar email"}, status_code=500)

@app.post("/api/import-personal-csv")
async def import_personal_csv(request: Request):
    form = await request.form()
    raw_csv = form.get("personal_csv_data", "").strip()
    if not raw_csv: return JSONResponse({"status": "error", "msg": "CSV vacío"})
    
    try:
        f = io.StringIO(raw_csv)
        reader = csv.DictReader(f)
        imported_count = 0
        for row in reader:
            nombre = row.get("Negocio", "").strip()
            if not nombre: continue
            
            lead = {
                "nombre": nombre,
                "rubro": row.get("Categoria", "General").strip(),
                "distrito": row.get("Distrito", "Lima").strip(),
                "plan_sugerido": "STARTER",
                "criterio_match": "Importación Manual CSV",
                "origen": "MANUAL_CSV",
                "estado": "Pendiente",
                "email": row.get("Email", "").strip(),
                "telefono": row.get("Telefono", "").strip(),
                "direccion_completa": row.get("Direccion", "").strip(),
                "pitch_automatizado": f"Hola {nombre}, tenemos una propuesta para ti.",
                "created_at": datetime.now().isoformat()
            }
            if insert_lead_supabase(lead):
                imported_count += 1
                
        return JSONResponse({"status": "success", "imported": imported_count})
    except Exception as e:
        logger.error(f"Error importando CSV: {e}")
        return JSONResponse({"status": "error", "msg": str(e)})

# --- EXPORTAR CSV CON 13 COLUMNAS EXACTAS ---

@app.get("/api/export-csv")
async def export_csv():
    if not supabase_connected:
        return JSONResponse({"error": "No conectado a Supabase"}, status_code=500)
        
    leads = get_leads("Pendiente")
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        "Categoria", "Distrito", "Negocio", "Direccion", "Rating", "Reseñas", 
        "Contacto", "Web/Redes", "Publico objetivo", "Puntos fuertes", 
        "Puntos debiles", "Presencia digital", "Responde reseñas"
    ])
    
    for lead in leads:
        writer.writerow([
            lead.get("rubro", ""),
            lead.get("distrito", ""),
            lead.get("nombre", ""),
            lead.get("direccion_completa", ""),
            "", "", lead.get("telefono", ""), "", lead.get("plan_sugerido", ""),
            "", lead.get("criterio_match", ""), "No", ""
        ])
        
    output.seek(0)
    
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_orasic_avanzado.csv"}
    )

# --- DASHBOARD VISUAL CON DROPDOWNS ---

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    leads_enviados = get_sent_count()
    leads_pendientes = get_leads("Pendiente")
    
    rows_html = ""
    for i, lead in enumerate(leads_pendientes, 1):
        email_dest = lead.get("email", "").strip()
        tel_dest = lead.get("telefono", "").strip()
        texto_msg = urllib.parse.quote(lead.get("pitch_automatizado", "Hola"))
        lead_id = lead.get("id")
        
        if email_dest:
            btn_accion = f"""
            <form action='/api/send-email/{lead_id}' method='POST' style='margin:0;'>
                <button type='submit' style='background:#7C3AED; color:white; padding:6px 12px; border:none; border-radius:6px; font-size:0.8rem; cursor:pointer;'>📧 Email</button>
            </form>
            """
        elif tel_dest:
            btn_accion = f"""
            <a href='https://wa.me/{tel_dest}?text={texto_msg}' target='_blank' 
               onclick='fetch(\"/api/mark-sent/{lead_id}\", {{method: \"POST\"}});' 
               style='background:#22C55E; color:white; padding:6px 12px; border-radius:6px; text-decoration:none; font-size:0.8rem; display:inline-block;'>💬 WhatsApp</a>
            """
        else:
            btn_accion = "<span style='color:#64748B;'>Sin Contacto</span>"
            
        rows_html += f"""
        <tr style="border-bottom: 1px solid #1E293B;">
            <td style="padding:12px; text-align:center; color:#64748B;">#{i}</td>
            <td style="padding:12px; font-weight:600; color:white;">{lead.get("nombre")}</td>
            <td style="padding:12px; color:#94A3B8;">{lead.get("rubro")}</td>
            <td style="padding:12px; color:#94A3B8;">{lead.get("distrito")}</td>
            <td style="padding:12px; color:#94A3B8;">{lead.get("telefono", "Sin número")}</td>
            <td style="padding:12px; text-align:center;"><span style="background:#22D3EE20; color:#22D3EE; padding:4px 10px; border-radius:12px; font-size:0.8rem;">{lead.get("plan_sugerido")}</span></td>
            <td style="padding:12px; text-align:center;">{btn_accion}</td>
        </tr>"""
    
    if not rows_html: rows_html = "<tr><td colspan='7' style='padding:30px; text-align:center; color:#64748B;'>No hay prospectos pendientes.</td></tr>"
    
    # Generar opciones de dropdowns
    rubro_options = "".join([f'<option value="{r}">{r}</option>' for r in RUBROS_NEGOCIOS])
    distrito_options = "".join([f'<option value="{d}">{d}</option>' for d in DISTRITOS_LIMA])
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>ORASIC Sales Machine</title>
        <style>
            body {{ background:#0F172A; color:white; font-family:sans-serif; padding:40px; margin:0; }}
            h2 {{ color:#A78BFA; }}
            table {{ width:100%; border-collapse:collapse; background:#1E293B; border-radius:8px; overflow:hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            th {{ background:#334155; color:#CBD5E1; padding:12px; text-align:left; }}
            tr:hover {{ background:#334155; }}
            .btn-export {{ background:#F59E0B; color:white; padding:10px 20px; text-decoration:none; border-radius:6px; font-weight:bold; display:inline-block; margin-bottom:20px; }}
            .search-box {{ background:#1E293B; padding:20px; border-radius:8px; margin-bottom:30px; display:flex; gap:10px; flex-wrap:wrap; align-items:end; }}
            select, input {{ padding:10px; border-radius:4px; border:1px solid #475569; background:#0F172A; color:white; flex:1; min-width:150px; }}
            button.search-btn {{ background:#A78BFA; color:white; border:none; padding:10px 20px; border-radius:4px; cursor:pointer; font-weight:bold; }}
            .other-input {{ display:none; margin-top:5px; }}
        </style>
        <script>
            function toggleOther(selectId, inputId) {{
                var select = document.getElementById(selectId);
                var input = document.getElementById(inputId);
                if (select.value === "Otro") {{
                    input.style.display = "block";
                    input.required = true;
                }} else {{
                    input.style.display = "none";
                    input.required = false;
                }}
            }}
        </script>
    </head>
    <body>
        <div style="max-width:1000px; margin:0 auto;">
            <h1 style="text-align:center; margin-bottom:40px;"> ORASIC Sales Machine</h1>
            
            <div class="search-box">
                <form action="/api/auto-search" method="post" style="display:flex; gap:10px; flex:1; flex-wrap:wrap;">
                    
                    <!-- Dropdown Rubro -->
                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:#94A3B8; display:block; margin-bottom:5px;">Rubro / Categoría</label>
                        <select name="keyword" id="keyword_select" onchange="toggleOther('keyword_select', 'keyword_other')" required>
                            <option value="" disabled selected>Selecciona un rubro</option>
                            {rubro_options}
                        </select>
                        <input type="text" id="keyword_other" name="keyword_other" placeholder="Escribe otro rubro..." class="other-input">
                    </div>

                    <!-- Dropdown Distrito -->
                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:#94A3B8; display:block; margin-bottom:5px;">Distrito / Ubicación</label>
                        <select name="location" id="location_select" onchange="toggleOther('location_select', 'location_other')" required>
                            <option value="" disabled selected>Selecciona un distrito</option>
                            {distrito_options}
                        </select>
                        <input type="text" id="location_other" name="location_other" placeholder="Escribe otro distrito..." class="other-input">
                    </div>

                    <div style="width:100px;">
                        <label style="font-size:0.8rem; color:#94A3B8; display:block; margin-bottom:5px;">Cantidad</label>
                        <input type="number" name="limit" value="20" min="1" max="100">
                    </div>

                    <button type="submit" class="search-btn">🔍 Buscar</button>
                </form>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; background:#1E293B; padding:20px; border-radius:8px;">
                <div><strong>Enviados:</strong> <span style="color:#22C55E; font-size:1.5rem;">{leads_enviados}</span></div>
                <div><strong>Pendientes:</strong> <span style="color:#F59E0B; font-size:1.5rem;">{len(leads_pendientes)}</span></div>
                <a href="/api/export-csv" class="btn-export"> Exportar CSV</a>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>#</th><th>Nombre</th><th>Negocio / Rubro</th><th>Distrito</th><th>WhatsApp</th><th>Plan Sugerido</th><th>Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
            
            <div style="margin-top:40px; text-align:center;">
                <p style="color:#64748B; font-size:0.9rem;">v4.0 • Dropdowns Inteligentes • Exportación Avanzada</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)