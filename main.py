from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
import os, logging, requests, json, csv, io, smtplib, urllib.parse, unicodedata, re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import google.generativeai as genai
import uvicorn
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

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
            
            # AUTO-REPARACIÓN DE ORIGEN AL INICIAR
            try:
                url_leads = f"{SUPABASE_URL}/rest/v1/leads?estado=eq.Pendiente&select=id,origen,direccion_completa"
                resp_leads = requests.get(url_leads, headers=headers, timeout=10)
                if resp_leads.status_code == 200:
                    leads_db = resp_leads.json()
                    for lead in leads_db:
                        current_origin = lead.get("origen", "")
                        if not current_origin or current_origin == "manual" or current_origin == "Desconocido":
                            new_origin = "GOOGLE_MAPS_LEGACY" if lead.get("direccion_completa") and len(lead.get("direccion_completa", "")) > 10 else "MANUAL_CSV"
                            if new_origin != current_origin:
                                update_url = f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead['id']}"
                                requests.patch(update_url, headers=headers, json={"origen": new_origin}, timeout=5)
                    logger.info(" Auto-reparación de orígenes completada.")
            except Exception as e_fix:
                logger.error(f"Error en auto-reparación: {e_fix}")
                
    except Exception as e:
        logger.error(f"❌ Excepción Supabase: {e}")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

# --- DICCIONARIO OPTIMIZADO PARA GOOGLE MAPS ---
TERMINOS_RELACIONADOS = {
    "Barbería": ["Barbería", "Barber Shop", "Barbershop", "Peluquería masculina"],
    "Clínica Dental": ["Clínica Dental", "Dentista", "Odontólogo", "Consultorio dental"],
    "Veterinaria": ["Veterinaria", "Clínica veterinaria", "Pet Shop", "Tienda de mascotas"],
    "Spa": ["Spa", "Masajes", "Masoterapia", "Relajación"],
    "Gimnasio": ["Gimnasio", "Gym", "Fitness", "CrossFit"],
    "Cancha de Fútbol": ["Cancha de Fútbol", "Fútbol 5", "Complejo deportivo"],
    "Salón de Belleza": ["Salón de Belleza", "Peluquería", "Estética", "Manicure"],
    "Pilates": ["Pilates", "Estudio de Pilates", "Yoga"],
    "Clínica Médica": ["Clínica Médica", "Centro Médico", "Policlínico"],
    "Agencia de Marketing": ["Agencia de Marketing", "Marketing Digital", "Publicidad"],
    "Academia de Inglés": ["Academia de Inglés", "Instituto de idiomas", "Británico", "ICPNA"],
    "Panadería": ["Panadería", "Pastelería", "Bakery", "Pan artesanal"]
}

RUBROS_NEGOCIOS = sorted(list(TERMINOS_RELACIONADOS.keys())) + ["Otro"]
DISTRITOS_LIMA = [
    "Ancón", "Ate", "Barranco", "Breña", "Carabayllo", "Chaclacayo", "Chorrillos", "Cieneguilla", "Comas", "El Agustino", "Independencia", "Jesús María", "La Molina", "La Victoria", "Lima", "Lince", "Los Olivos", "Lurigancho", "Lurín", "Magdalena del Mar", "Miraflores", "Pachacámac", "Pucusana", "Pueblo Libre", "Puente Piedra", "Punta Hermosa", "Punta Negra", "Rímac", "San Bartolo", "San Borja", "San Isidro", "San Juan de Lurigancho", "San Juan de Miraflores", "San Luis", "San Martín de Porres", "San Miguel", "Santa Anita", "Santa María del Mar", "Santa Rosa", "Santiago de Surco", "Surquillo", "Villa El Salvador", "Villa María del Triunfo", "Otro"
]

# --- FUNCIONES AUXILIARES ---

def normalizar_agresivo(texto):
    if not texto: return ""
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().strip()
    texto = re.sub(r'\s+', ' ', texto)
    return texto

def get_leads(status="Pendiente"):
    if not supabase_connected: return []
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        url = f"{SUPABASE_URL}/rest/v1/leads?estado=eq.{status}&limit=500"
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json() if resp.status_code == 200 else []
    except: return []

def get_sent_count():
    if not supabase_connected: return 0
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Prefer": "count=exact"}
        resp = requests.get(f"{SUPABASE_URL}/rest/v1/leads?estado=eq.Enviado&select=id", headers=headers, timeout=5)
        range_header = resp.headers.get('Content-Range', '')
        return int(range_header.split('/')[-1]) if '/' in range_header else 0
    except: return 0

def insert_lead_supabase(lead):
    if not supabase_connected: return False
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/leads", headers=headers, json=lead, timeout=5)
        return resp.status_code >= 200 and resp.status_code < 300
    except: return False

def search_leads_google_expanded(keyword, location, limit=100):
    GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_KEY: return []
    
    terminos_busqueda = [keyword]
    keyword_clean = keyword.strip()
    
    for categoria, sinonimos in TERMINOS_RELACIONADOS.items():
        if categoria.lower() == keyword_clean.lower():
            terminos_busqueda = sinonimos
            break
    
    terminos_unicos = list(dict.fromkeys(terminos_busqueda))
    all_leads = []
    existing_leads = get_leads("Pendiente") + get_leads("Enviado")
    
    # CONSTRUCCIÓN EXPLÍCITA DE CLAVES (NOMBRE + DISTRITO)
    existing_keys = set()
    for l in existing_leads:
        n = normalizar_agresivo(l.get('nombre', ''))
        d = normalizar_agresivo(l.get('distrito', ''))
        existing_keys.add((n, d))
        
    logger.info(f"📊 Cargadas {len(existing_keys)} combinaciones únicas (Nombre+Distrito) de la BD")
    
    for termino in terminos_unicos:
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json", 
            "X-Goog-Api-Key": GOOGLE_KEY, 
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.primaryType,places.internationalPhoneNumber"
        }
        payload = {"textQuery": f"{termino} en {location}", "maxResultCount": min(limit, 50), "languageCode": "es"}
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=12)
            if resp.status_code != 200: continue
            places = resp.json().get("places", [])
            
            for place in places:
                name = place.get("displayName", {}).get("text", "").strip()
                if not name: continue
                
                name_norm = normalizar_agresivo(name)
                loc_norm = normalizar_agresivo(location)
                current_key = (name_norm, loc_norm)
                
                # VERIFICACIÓN ESTRICTA: Solo es duplicado si AMBOS coinciden
                is_duplicate = current_key in existing_keys
                
                tel = place.get("internationalPhoneNumber", "").replace(" ", "").replace("-", "")
                lead = {
                    "nombre": name, 
                    "rubro": keyword_clean,
                    "distrito": location.title(), 
                    "plan_sugerido": "STARTER",  
                    "criterio_match": f"Búsqueda: '{termino}'", 
                    "origen": "GOOGLE_MAPS_EXPANDED", 
                    "estado": "Pendiente",
                    "email": "",
                    "telefono": tel,
                    "direccion_completa": place.get("formattedAddress", ""), 
                    "pitch_automatizado": f"Hola equipo de {name}, soy Fernando de ORASIC Lab. Vi su negocio en {location}.",
                    "es_duplicado": is_duplicate,
                    "created_at": datetime.now().isoformat()
                }
                all_leads.append(lead)
                
                if not is_duplicate:
                    existing_keys.add(current_key)
                
                if len(all_leads) >= limit: break
            if len(all_leads) >= limit: break
        except: continue
            
    return all_leads[:limit]

@app.post("/api/auto-search")
async def auto_search(request: Request):
    form = await request.form()
    keyword = form.get("keyword", "")
    location = form.get("location", "")
    limit = min(int(form.get("limit", 100)), 100)
    
    if keyword == "Otro": keyword = form.get("keyword_other", "").strip()
    if location == "Otro": location = form.get("location_other", "").strip()

    if not keyword or not location:
        return RedirectResponse(url="/?error=Faltan+datos", status_code=303)

    new_leads = search_leads_google_expanded(keyword, location, limit)
    
    count_inserted = 0
    for lead in new_leads:
        if not lead.get("es_duplicado"):
            if insert_lead_supabase(lead):
                count_inserted += 1
    
    preview_leads = new_leads[:5]
    preview_json = json.dumps(preview_leads)
    encoded_preview = urllib.parse.quote(preview_json)
    
    msg = f"Busqué '{keyword}' en '{location}'. {len(new_leads)} encontrados. {count_inserted} guardados (nuevos). {len(new_leads)-count_inserted} duplicados."
    
    return RedirectResponse(url=f"/?success={urllib.parse.quote(msg)}&last_keyword={urllib.parse.quote(keyword)}&last_location={urllib.parse.quote(location)}&preview={encoded_preview}", status_code=303)

@app.get("/", response_class=HTMLResponse)
async def dashboard(success: str = None, error: str = None, filter_origin: str = None, last_keyword: str = None, last_location: str = None, preview: str = None):
    leads_enviados = get_sent_count()
    all_leads_pendientes = get_leads("Pendiente")
    
    if filter_origin == "google":
        leads_pendientes = [l for l in all_leads_pendientes if "GOOGLE" in l.get("origen", "").upper()]
        filter_label = "Solo Google Maps"
    elif filter_origin == "manual":
        leads_pendientes = [l for l in all_leads_pendientes if l.get("origen", "") == "MANUAL_CSV"]
        filter_label = "Solo Manuales"
    else:
        leads_pendientes = all_leads_pendientes
        filter_label = "Todos"
    
    alert_html = ""
    preview_html = ""
    
    if success:
        alert_html = f"<div style='background:#064E3B;border-left:4px solid #10B981;color:#ECFDF5;padding:15px;margin-bottom:20px;'>✅ {urllib.parse.unquote(success)}</div>"
        
        if preview:
            try:
                preview_data = json.loads(urllib.parse.unquote(preview))
                rows_preview = ""
                for p in preview_data:
                    dup_badge = "<span style='color:#EF4444;font-size:0.7rem;'> (Duplicado)</span>" if p.get("es_duplicado") else "<span style='color:#10B981;font-size:0.7rem;'> (Nuevo)</span>"
                    rows_preview += f"<tr style='border-bottom:1px solid #334155;'><td style='padding:8px;'>{p['nombre']}{dup_badge}</td><td>{p['rubro']}</td><td>{p['distrito']}</td><td>{p.get('telefono','Sin número')}</td></tr>"
                
                preview_html = f"""
                <div style='background:#1E293B;padding:20px;border-radius:8px;margin-bottom:20px;border:1px solid #475569;'>
                    <h3 style='margin-top:0;color:#A78BFA;'>🔍 Resultados de la última búsqueda (Primeros 5)</h3>
                    <table style='width:100%;font-size:0.9rem;'>
                        <thead><tr style='color:#94A3B8;'><th>Nombre</th><th>Rubro</th><th>Distrito</th><th>Teléfono</th></tr></thead>
                        <tbody>{rows_preview}</tbody>
                    </table>
                </div>
                """
            except: pass

    elif error:
        alert_html = f"<div style='background:#7F1D1D;border-left:4px solid #EF4444;color:#FEF2F2;padding:15px;margin-bottom:20px;'>❌ {urllib.parse.unquote(error)}</div>"
    
    rows_html = ""
    for i, lead in enumerate(leads_pendientes, 1):
        email_dest = lead.get("email", "").strip()
        tel_dest = lead.get("telefono", "").strip()
        texto_msg = urllib.parse.quote(lead.get("pitch_automatizado", "Hola"))
        lead_id = lead.get("id")
        origen = lead.get("origen", "Desconocido")
        
        if "GOOGLE" in origen.upper():
            origen_badge = '<span style="background:#3B82F620;color:#3B82F6;padding:2px 8px;border-radius:4px;font-size:0.7rem;">🔍 Google</span>'
        elif origen == "MANUAL_CSV":
            origen_badge = '<span style="background:#F59E0B20;color:#F59E0B;padding:2px 8px;border-radius:4px;font-size:0.7rem;">📁 Manual</span>'
        else:
            origen_badge = '<span style="background:#64748B20;color:#64748B;padding:2px 8px;border-radius:4px;font-size:0.7rem;">❓ Otro</span>'
        
        btn_accion = ""
        if email_dest:
            btn_accion = f"<form action='/api/send-email/{lead_id}' method='POST' style='margin:0;'><button style='background:#7C3AED;color:white;padding:6px 12px;border:none;border-radius:6px;'>📧 Email</button></form>"
        elif tel_dest:
            btn_accion = f"<a href='https://wa.me/{tel_dest}?text={texto_msg}' target='_blank' onclick='fetch(\"/api/mark-sent/{lead_id}\",{{method:\"POST\"}});' style='background:#22C55E;color:white;padding:6px 12px;border-radius:6px;text-decoration:none;display:inline-block;'>💬 WA</a>"
        else:
            btn_accion = "<span style='color:#64748B;'>Sin Contacto</span>"
            
        rows_html += f"<tr style='border-bottom:1px solid #1E293B;'><td style='padding:12px;'>#{i}</td><td style='font-weight:600;'>{lead.get('nombre')}</td><td>{lead.get('rubro')}</td><td>{lead.get('distrito')}</td><td>{lead.get('telefono','Sin número')}</td><td><span style='background:#22D3EE20;color:#22D3EE;padding:4px 10px;border-radius:12px;font-size:0.8rem;'>{lead.get('plan_sugerido')}</span></td><td>{origen_badge}</td><td>{btn_accion}</td></tr>"
    
    if not rows_html: rows_html = "<tr><td colspan='8' style='padding:30px;text-align:center;'>No hay prospectos.</td></tr>"
    
    rubro_options = "".join([f'<option value="{r}" {"selected" if r == last_keyword else ""}>{r}</option>' for r in RUBROS_NEGOCIOS])
    distrito_options = "".join([f'<option value="{d}" {"selected" if d == last_location else ""}>{d}</option>' for d in DISTRITOS_LIMA])
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>ORASIC Sales Machine</title>
        <style>
            body {{ background:#0F172A; color:white; font-family:sans-serif; padding:40px; margin:0; }}
            table {{ width:100%; border-collapse:collapse; background:#1E293B; border-radius:8px; overflow:hidden; }}
            th {{ background:#334155; color:#CBD5E1; padding:12px; text-align:left; }}
            tr:hover {{ background:#334155; }}
            .btn-export {{ background:#F59E0B; color:white; padding:10px 20px; text-decoration:none; border-radius:6px; font-weight:bold; display:inline-block; }}
            .search-box {{ background:#1E293B; padding:20px; border-radius:8px; margin-bottom:30px; display:flex; gap:10px; flex-wrap:wrap; align-items:end; }}
            select, input {{ padding:10px; border-radius:4px; border:1px solid #475569; background:#0F172A; color:white; flex:1; min-width:150px; }}
            button.search-btn {{ background:#A78BFA; color:white; border:none; padding:10px 20px; border-radius:4px; cursor:pointer; font-weight:bold; }}
            .other-input {{ display:none; margin-top:5px; }}
            .filter-buttons {{ display:flex; gap:10px; margin-bottom:20px; }}
            .filter-btn {{ background:#1E293B; color:#CBD5E1; padding:8px 16px; border-radius:6px; text-decoration:none; border:1px solid #475569; }}
            .filter-btn.active {{ background:#A78BFA; color:white; border-color:#A78BFA; }}
        </style>
        <script>
            function toggleOther(sId, iId) {{ var s=document.getElementById(sId); var i=document.getElementById(iId); if(s.value==="Otro"){{i.style.display="block";i.required=true;}}else{{i.style.display="none";i.required=false;}} }}
        </script>
    </head>
    <body>
        <div style="max-width:1200px; margin:0 auto;">
            <h1 style="text-align:center;">🤖 ORASIC Sales Machine</h1>
            {alert_html}
            {preview_html}
            <div class="search-box">
                <form action="/api/auto-search" method="post" style="display:flex; gap:10px; flex:1; flex-wrap:wrap;">
                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:#94A3B8;">Categoría (Google Maps)</label>
                        <select name="keyword" id="keyword_select" onchange="toggleOther('keyword_select', 'keyword_other')" required>
                            <option value="" disabled selected>Selecciona...</option>
                            {rubro_options}
                        </select>
                        <input type="text" id="keyword_other" name="keyword_other" placeholder="Otro..." class="other-input">
                    </div>
                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:#94A3B8;">Distrito</label>
                        <select name="location" id="location_select" onchange="toggleOther('location_select', 'location_other')" required>
                            <option value="" disabled selected>Selecciona...</option>
                            {distrito_options}
                        </select>
                        <input type="text" id="location_other" name="location_other" placeholder="Otro..." class="other-input">
                    </div>
                    <div style="width:100px;">
                        <label style="font-size:0.8rem; color:#94A3B8;">Cantidad</label>
                        <input type="number" name="limit" value="100" min="1" max="100">
                    </div>
                    <button type="submit" class="search-btn">🔍 Buscar</button>
                </form>
            </div>
            <div class="filter-buttons">
                <a href="/?filter_origin=all" class="filter-btn {'active' if filter_origin == 'all' or not filter_origin else ''}"> Todos ({len(all_leads_pendientes)})</a>
                <a href="/?filter_origin=google" class="filter-btn {'active' if filter_origin == 'google' else ''}">🔍 Google ({len([l for l in all_leads_pendientes if 'GOOGLE' in l.get('origen','').upper()])})</a>
                <a href="/?filter_origin=manual" class="filter-btn {'active' if filter_origin == 'manual' else ''}">📁 Manual ({len([l for l in all_leads_pendientes if l.get('origen','')=='MANUAL_CSV'])})</a>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; background:#1E293B; padding:20px; border-radius:8px;">
                <div><strong>Enviados:</strong> <span style="color:#22C55E; font-size:1.5rem;">{leads_enviados}</span></div>
                <div><strong>Pendientes ({filter_label}):</strong> <span style="color:#F59E0B; font-size:1.5rem;">{len(leads_pendientes)}</span></div>
                <a href="/api/export-excel" class="btn-export">📥 Exportar Excel</a>
            </div>
            <table>
                <thead><tr><th>#</th><th>Nombre</th><th>Rubro</th><th>Distrito</th><th>WhatsApp</th><th>Plan</th><th>Origen</th><th>Acción</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
            <div style="margin-top:40px; text-align:center;">
                <p style="color:#64748B;">v9.4 • Lógica de Duplicados Corregida • Memoria de Búsqueda • Previsualización</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/mark-sent/{lead_id}")
async def mark_sent(lead_id: str):
    if not supabase_connected: return JSONResponse({"status": "error"}, status_code=500)
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
        url = f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}"
        resp = requests.patch(url, headers=headers, json={"estado": "Enviado"}, timeout=5)
        return JSONResponse({"status": "success"})
    except: return JSONResponse({"status": "error"}, status_code=500)

@app.post("/api/send-email/{lead_id}")
async def send_email_route(lead_id: str):
    if not supabase_connected or not SMTP_PASSWORD: return JSONResponse({"status": "error"}, status_code=500)
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        url = f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200 or not resp.json(): return JSONResponse({"status": "error"}, status_code=404)
        lead = resp.json()[0]
        email_dest = lead.get("email", "").strip()
        if not email_dest: return JSONResponse({"status": "error"}, status_code=400)
        
        msg = MIMEMultipart()
        msg["From"] = SMTP_EMAIL
        msg["To"] = email_dest
        msg["Subject"] = f"Propuesta para {lead.get('nombre')}"
        msg.attach(MIMEText(lead.get("pitch_automatizado", ""), "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, email_dest, msg.as_string())
        server.quit()
        
        update_lead_status(lead_id, "Enviado")
        return JSONResponse({"status": "success"})
    except: return JSONResponse({"status": "error"}, status_code=500)

@app.get("/api/export-excel")
async def export_excel():
    if not supabase_connected: return JSONResponse({"error": "No conectado"}, status_code=500)
    leads = get_leads("Pendiente")
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads Pendientes"
    headers = ["Categoria", "Distrito", "Negocio", "Direccion", "Rating", "Reseñas", "Contacto", "Web/Redes", "Publico objetivo", "Puntos fuertes", "Puntos debiles", "Presencia digital", "Responde reseñas"]
    ws.append(headers)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
    for lead in leads:
        ws.append([lead.get("rubro", ""), lead.get("distrito", ""), lead.get("nombre", ""), lead.get("direccion_completa", ""), "", "", lead.get("telefono", ""), "", lead.get("plan_sugerido", ""), "", lead.get("criterio_match", ""), "No", ""])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=leads_orasic.xlsx"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)