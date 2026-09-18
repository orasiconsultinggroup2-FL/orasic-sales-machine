from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
import os, logging, requests, json, csv, io, smtplib, urllib.parse, unicodedata
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
    except Exception as e:
        logger.error(f"❌ Excepción Supabase: {e}")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

# --- DICCIONARIO DE SINÓNIMOS/TÉRMINOS RELACIONADOS POR CATEGORÍA ---

TERMINOS_RELACIONADOS = {
    "mascotas": [
        "Pet Shops", "Veterinarias", "Tienda de mascotas", "Alimentos para perros", 
        "Accesorios para mascotas", "Peluquería canina", "Hospedaje para mascotas", 
        "Guardería canina", "Entrenamiento de perros", "Clínica veterinaria",
        "Farmacia veterinaria", "Juguetes para mascotas", "Ropa para perros"
    ],
    "belleza": [
        "Barberías", "Peluquerías", "Salones de belleza", "Estéticas", 
        "Manicure", "Pedicure", "Spa", "Maquillaje", "Depilación",
        "Tratamientos faciales", "Uñas acrílicas", "Extensiones de pestañas"
    ],
    "salud": [
        "Clínicas", "Consultorios médicos", "Dentistas", "Odontólogos",
        "Laboratorios clínicos", "Farmacias", "Centros de salud", 
        "Fisioterapia", "Quiropráctica", "Nutricionistas", "Psicólogos"
    ],
    "comida": [
        "Restaurantes", "Cafeterías", "Bares", "Discotecas", "Comida rápida",
        "Pizzerías", "Hamburgueserías", "Sushi", "Mariscos", "Pollerías",
        "Chifas", "Postres", "Heladerías", "Panaderías", "Pastelerías"
    ],
    "fitness": [
        "Gimnasios", "CrossFit", "Yoga", "Pilates", "Centros deportivos",
        "Canchas de fútbol", "Canchas de tenis", "Piscinas", "Spa deportivo",
        "Entrenadores personales", "Artes marciales", "Boxeo", "Danza"
    ],
    "educacion": [
        "Colegios", "Academias", "Universidades", "Institutos", "Guarderías",
        "Centros de idiomas", "Capacitación", "Talleres", "Cursos",
        "Bibliotecas", "Ludotecas", "Centros de estudio"
    ],
    "automotriz": [
        "Talleres mecánicos", "Lavaderos de autos", "Repuestos", "Neumáticos",
        "Concesionarios", "Seguros automotrices", "Alquiler de autos",
        "Pintura automotriz", "Electrónica automotriz", "Detailing"
    ],
    "construccion": [
        "Constructoras", "Arquitectos", "Inmobiliarias", "Ferreterías",
        "Materiales de construcción", "Pinturerías", "Cerrajerías",
        "Electricistas", "Plomeros", "Albañiles", "Diseño de interiores"
    ],
    "tecnologia": [
        "Tiendas de computadoras", "Reparación de celulares", "Imprentas",
        "Diseño gráfico", "Marketing digital", "Desarrollo web",
        "Soporte técnico", "Redes", "Seguridad informática", "Videojuegos"
    ],
    "ropa": [
        "Tiendas de ropa", "Zapaterías", "Boutiques", "Moda", "Calzado",
        "Accesorios de moda", "Joyerías", "Relojerías", "Lencería",
        "Ropa deportiva", "Uniformes", "Disfraces", "Costureras"
    ]
}

# --- LISTAS PREDEFINIDAS PARA DROPDOWNS ---

RUBROS_NEGOCIOS = list(TERMINOS_RELACIONADOS.keys()) + ["Otro"]

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

def normalizar_texto(texto):
    """Elimina tildes, convierte a minúsculas y quita espacios extra"""
    if not texto:
        return ""
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return texto.lower().strip()

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

# --- MOTOR DE BÚSQUEDA INTELIGENTE CON EXPANSIÓN DE TÉRMINOS ---

def search_leads_google_expanded(keyword, location, limit=100):
    GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_KEY: return []
    
    terminos_busqueda = [keyword]
    keyword_lower = keyword.lower().strip()
    
    for categoria, sinonimos in TERMINOS_RELACIONADOS.items():
        if categoria in keyword_lower or any(sinonimo.lower() in keyword_lower for sinonimo in sinonimos):
            terminos_busqueda.extend(sinonimos)
            break
    
    terminos_unicos = []
    for t in terminos_busqueda:
        if t.lower() not in [x.lower() for x in terminos_unicos]:
            terminos_unicos.append(t)
    
    logger.info(f"🔍 Buscando '{keyword}' en '{location}'. Términos expandidos: {terminos_unicos}")
    
    all_leads = []
    existing_leads = get_leads("Pendiente") + get_leads("Enviado")
    
    # CORRECCIÓN: Usar tupla (nombre_normalizado, distrito_normalizado) para detectar duplicados
    existing_keys = set()
    for l in existing_leads:
        nombre_norm = normalizar_texto(l.get('nombre', ''))
        distrito_norm = normalizar_texto(l.get('distrito', ''))
        existing_keys.add((nombre_norm, distrito_norm))
    
    logger.info(f"📊 Leads existentes en BD: {len(existing_leads)}")
    
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
            if resp.status_code != 200: 
                logger.warning(f"⚠️ Google Maps devolvió status {resp.status_code} para '{termino}'")
                continue
                
            places = resp.json().get("places", [])
            logger.info(f"✅ Google encontró {len(places)} lugares para '{termino}' en {location}")
            
            for place in places:
                name = place.get("displayName", {}).get("text", "").strip()
                if not name:
                    continue
                    
                # CORRECCIÓN: Normalizar nombre y distrito antes de comparar
                name_normalized = normalizar_texto(name)
                location_normalized = normalizar_texto(location)
                lead_key = (name_normalized, location_normalized)
                
                if lead_key in existing_keys:
                    logger.debug(f"️ DUPLICADO DETECTADO: '{name}' en '{location}' ya existe en BD")
                    continue
                
                tel = place.get("internationalPhoneNumber", "").replace(" ", "").replace("-", "")
                pitch_simple = f"Hola equipo de {name}, soy Fernando de ORASIC Lab. Vi su negocio en {location} y tengo una propuesta digital para potenciar sus ventas."

                lead = {
                    "nombre": name, 
                    "rubro": termino.capitalize(), 
                    "distrito": location.title(), 
                    "plan_sugerido": "STARTER",  
                    "criterio_match": f"Búsqueda expandida: '{keyword}' → '{termino}'", 
                    "origen": "GOOGLE_MAPS_EXPANDED", 
                    "estado": "Pendiente",
                    "email": "",
                    "telefono": tel,
                    "direccion_completa": place.get("formattedAddress", ""), 
                    "pitch_automatizado": pitch_simple,
                    "datos_originales": {"Categoria": termino, "Distrito": location, "Negocio": name, "Direccion": place.get("formattedAddress", ""), "BusquedaOriginal": keyword},
                    "created_at": datetime.now().isoformat()
                }
                all_leads.append(lead)
                
                # CORRECCIÓN: Agregar inmediatamente para evitar duplicados en la misma búsqueda
                existing_keys.add(lead_key)
                logger.info(f"💾 Lead agregado: {name} en {location} ({termino})")
                
                if len(all_leads) >= limit:
                    logger.info(f"🛑 Límite de {limit} leads alcanzado")
                    break
                    
            if len(all_leads) >= limit:
                break
                
        except Exception as e:
            logger.error(f"❌ Error buscando '{termino}': {e}")
            continue
            
    logger.info(f"🎯 TOTAL ENCONTRADOS: {len(all_leads)} leads NUEVOS para '{keyword}' en {location}")
    return all_leads[:limit]

# --- RUTAS DE LA API ---

@app.post("/api/auto-search")
async def auto_search(request: Request):
    form = await request.form()
    keyword = form.get("keyword", "")
    location = form.get("location", "")
    
    # CAMBIO: Límite máximo 100, valor por defecto 100
    limit = min(int(form.get("limit", 100)), 100)
    
    if keyword == "Otro":
        keyword = form.get("keyword_other", "").strip()
    if location == "Otro":
        location = form.get("location_other", "").strip()

    if not keyword or not location:
        return RedirectResponse(url="/?error=Faltan+datos", status_code=303)

    # Ejecutar búsqueda inteligente
    new_leads = search_leads_google_expanded(keyword, location, limit)
    
    count_inserted = 0
    for lead in new_leads:
        if insert_lead_supabase(lead):
            count_inserted += 1
            
    # GUARDAR BÚSQUEDA EN HISTORIAL
    try:
        history_headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
        history_payload = {
            "keyword": keyword,
            "location": location,
            "timestamp": datetime.now().isoformat(),
            "results_count": len(new_leads),
            "saved_count": count_inserted
        }
        requests.post(f"{SUPABASE_URL}/rest/v1/search_history", headers=history_headers, json=history_payload, timeout=5)
    except:
        pass  # Si falla, no interrumpimos el flujo principal
    
    message = f"Búsqueda inteligente completada. Busqué '{keyword}' en '{location}' y términos relacionados. {len(new_leads)} encontrados, {count_inserted} guardados como nuevos."
    encoded_message = urllib.parse.quote(message)
    
    return RedirectResponse(url=f"/?success={encoded_message}", status_code=303)

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

# --- EXPORTAR A EXCEL (.XLSX) ---

@app.get("/api/export-excel")
async def export_excel():
    if not supabase_connected:
        return JSONResponse({"error": "No conectado a Supabase"}, status_code=500)
        
    leads = get_leads("Pendiente")
    
    # Crear libro de Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads Pendientes"
    
    # Encabezados exactos que pediste
    headers = [
        "Categoria", "Distrito", "Negocio", "Direccion", "Rating", "Reseñas", 
        "Contacto", "Web/Redes", "Publico objetivo", "Puntos fuertes", 
        "Puntos debiles", "Presencia digital", "Responde reseñas"
    ]
    ws.append(headers)
    
    # Estilos opcionales para encabezados (negrita y fondo gris)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        
    # Llenar datos
    for lead in leads:
        row = [
            lead.get("rubro", ""),                # Categoria
            lead.get("distrito", ""),             # Distrito
            lead.get("nombre", ""),               # Negocio
            lead.get("direccion_completa", ""),   # Direccion
            "",                                   # Rating
            "",                                   # Reseñas
            lead.get("telefono", ""),             # Contacto
            "",                                   # Web/Redes
            lead.get("plan_sugerido", ""),        # Publico objetivo
            "",                                   # Puntos fuertes
            lead.get("criterio_match", ""),       # Puntos debiles
            "No",                                 # Presencia digital
            ""                                    # Responde reseñas
        ]
        ws.append(row)
        
    # Guardar en memoria
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    # Retornar como archivo descargable .xlsx
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=leads_orasic.xlsx"}
    )

# --- HISTORIAL DE BÚSQUEDAS ---

@app.get("/historial", response_class=HTMLResponse)
async def search_history():
    if not supabase_connected:
        return HTMLResponse("<h1>Error: No conectado a Supabase</h1>")
    
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(f"{SUPABASE_URL}/rest/v1/search_history?order=timestamp.desc&limit=50", headers=headers, timeout=5)
        history = resp.json() if resp.status_code == 200 else []
    except:
        history = []
    
    rows_html = ""
    for i, h in enumerate(history, 1):
        rows_html += f"""
        <tr style="border-bottom: 1px solid #1E293B;">
            <td style="padding:12px; text-align:center; color:#64748B;">#{i}</td>
            <td style="padding:12px; color:white;">{h.get('keyword', '')}</td>
            <td style="padding:12px; color:#94A3B8;">{h.get('location', '')}</td>
            <td style="padding:12px; color:#94A3B8;">{h.get('timestamp', '')[:19]}</td>
            <td style="padding:12px; text-align:center;"><span style="background:#3B82F620; color:#3B82F6; padding:4px 10px; border-radius:12px; font-size:0.8rem;">{h.get('results_count', 0)}</span></td>
            <td style="padding:12px; text-align:center;"><span style="background:#10B98120; color:#10B981; padding:4px 10px; border-radius:12px; font-size:0.8rem;">{h.get('saved_count', 0)}</span></td>
            <td style="padding:12px; text-align:center;">
                <form action="/api/auto-search" method="post" style="margin:0; display:inline;">
                    <input type="hidden" name="keyword" value="{h.get('keyword', '')}">
                    <input type="hidden" name="location" value="{h.get('location', '')}">
                    <input type="hidden" name="limit" value="100">
                    <button type="submit" style="background:#A78BFA; color:white; padding:6px 12px; border:none; border-radius:6px; font-size:0.8rem; cursor:pointer;">🔄 Repetir</button>
                </form>
            </td>
        </tr>"""
    
    if not rows_html: rows_html = "<tr><td colspan='7' style='padding:30px; text-align:center; color:#64748B;'>No hay búsquedas previas.</td></tr>"
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Historial de Búsquedas - ORASIC</title>
        <style>
            body {{ background:#0F172A; color:white; font-family:sans-serif; padding:40px; margin:0; }}
            table {{ width:100%; border-collapse:collapse; background:#1E293B; border-radius:8px; overflow:hidden; }}
            th {{ background:#334155; color:#CBD5E1; padding:12px; text-align:left; }}
            tr:hover {{ background:#334155; }}
            .back-btn {{ background:#64748B; color:white; padding:10px 20px; text-decoration:none; border-radius:6px; display:inline-block; margin-bottom:20px; }}
        </style>
    </head>
    <body>
        <div style="max-width:1000px; margin:0 auto;">
            <a href="/" class="back-btn">← Volver al Dashboard</a>
            <h1 style="text-align:center; margin-bottom:40px;">📜 Historial de Búsquedas</h1>
            
            <table>
                <thead>
                    <tr>
                        <th>#</th><th>Categoría</th><th>Distrito</th><th>Fecha</th><th>Encontrados</th><th>Guardados</th><th>Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# --- DASHBOARD VISUAL CON ORIGEN Y FILTROS ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(success: str = None, error: str = None, filter_origin: str = None):
    leads_enviados = get_sent_count()
    all_leads_pendientes = get_leads("Pendiente")
    
    # Filtrar por origen si se solicita
    if filter_origin == "google":
        leads_pendientes = [l for l in all_leads_pendientes if l.get("origen", "").startswith("GOOGLE")]
        filter_label = "Solo Google Maps"
    elif filter_origin == "manual":
        leads_pendientes = [l for l in all_leads_pendientes if l.get("origen", "") == "MANUAL_CSV"]
        filter_label = "Solo Importación Manual"
    else:
        leads_pendientes = all_leads_pendientes
        filter_label = "Todos"
    
    # Generar mensajes de alerta
    alert_html = ""
    if success:
        alert_html = f"""
        <div style="background:#064E3B; border-left:4px solid #10B981; color:#ECFDF5; padding:15px; margin-bottom:20px; border-radius:4px;">
            ✅ {urllib.parse.unquote(success)}
        </div>
        """
    elif error:
        alert_html = f"""
        <div style="background:#7F1D1D; border-left:4px solid #EF4444; color:#FEF2F2; padding:15px; margin-bottom:20px; border-radius:4px;">
            ❌ {urllib.parse.unquote(error)}
        </div>
        """
    
    rows_html = ""
    for i, lead in enumerate(leads_pendientes, 1):
        email_dest = lead.get("email", "").strip()
        tel_dest = lead.get("telefono", "").strip()
        texto_msg = urllib.parse.quote(lead.get("pitch_automatizado", "Hola"))
        lead_id = lead.get("id")
        origen = lead.get("origen", "Desconocido")
        
        # Badge de origen
        if origen.startswith("GOOGLE"):
            origen_badge = '<span style="background:#3B82F620; color:#3B82F6; padding:2px 8px; border-radius:4px; font-size:0.7rem;">🔍 Google</span>'
        elif origen == "MANUAL_CSV":
            origen_badge = '<span style="background:#F59E0B20; color:#F59E0B; padding:2px 8px; border-radius:4px; font-size:0.7rem;">📁 Manual</span>'
        else:
            origen_badge = '<span style="background:#64748B20; color:#64748B; padding:2px 8px; border-radius:4px; font-size:0.7rem;">❓ Otro</span>'
        
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
            <td style="padding:12px; text-align:center;">{origen_badge}</td>
            <td style="padding:12px; text-align:center;">{btn_accion}</td>
        </tr>"""
    
    if not rows_html: rows_html = "<tr><td colspan='8' style='padding:30px; text-align:center; color:#64748B;'>No hay prospectos pendientes.</td></tr>"
    
    rubro_options = "".join([f'<option value="{r}">{r.title()}</option>' for r in RUBROS_NEGOCIOS])
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
            .info-box {{ background:#1E293B; padding:15px; border-radius:8px; margin-bottom:20px; border-left: 4px solid #A78BFA; }}
            .info-box p {{ margin:0; color:#CBD5E1; font-size:0.9rem; }}
            .filter-buttons {{ display:flex; gap:10px; margin-bottom:20px; }}
            .filter-btn {{ background:#1E293B; color:#CBD5E1; padding:8px 16px; border-radius:6px; text-decoration:none; border:1px solid #475569; transition:all 0.2s; }}
            .filter-btn.active {{ background:#A78BFA; color:white; border-color:#A78BFA; }}
            .filter-btn:hover {{ background:#334155; }}
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
        <div style="max-width:1200px; margin:0 auto;">
            <h1 style="text-align:center; margin-bottom:40px;">🤖 ORASIC Sales Machine</h1>
            
            {alert_html}
            
            <div class="info-box">
                <p>💡 <strong>Búsqueda Inteligente:</strong> Cuando seleccionas una categoría (ej: "mascotas"), el sistema busca automáticamente todos los términos relacionados (Pet Shops, Veterinarias, Tiendas de mascotas, etc.) para encontrar más negocios.</p>
            </div>
            
            <div class="search-box">
                <form action="/api/auto-search" method="post" style="display:flex; gap:10px; flex:1; flex-wrap:wrap;">
                    
                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:#94A3B8; display:block; margin-bottom:5px;">Categoría de Negocio</label>
                        <select name="keyword" id="keyword_select" onchange="toggleOther('keyword_select', 'keyword_other')" required>
                            <option value="" disabled selected>Selecciona una categoría</option>
                            {rubro_options}
                        </select>
                        <input type="text" id="keyword_other" name="keyword_other" placeholder="Escribe otra categoría..." class="other-input">
                    </div>

                    <div style="flex:1; min-width:200px;">
                        <label style="font-size:0.8rem; color:#94A3B8; display:block; margin-bottom:5px;">Distrito / Ubicación</label>
                        <select name="location" id="location_select" onchange="toggleOther('location_select', 'location_other')" required>
                            <option value="" disabled selected>Selecciona un distrito</option>
                            {distrito_options}
                        </select>
                        <input type="text" id="location_other" name="location_other" placeholder="Escribe otro distrito..." class="other-input">
                    </div>

                    <!-- CAMBIO: Valor por defecto 100, máximo 100 -->
                    <div style="width:100px;">
                        <label style="font-size:0.8rem; color:#94A3B8; display:block; margin-bottom:5px;">Cantidad</label>
                        <input type="number" name="limit" value="100" min="1" max="100">
                    </div>

                    <button type="submit" class="search-btn">🔍 Buscar Inteligente</button>
                </form>
            </div>

            <!-- BOTONES DE FILTRO -->
            <div class="filter-buttons">
                <a href="/?filter_origin=all" class="filter-btn {'active' if filter_origin == 'all' or filter_origin == None else ''}"> Todos ({len(all_leads_pendientes)})</a>
                <a href="/?filter_origin=google" class="filter-btn {'active' if filter_origin == 'google' else ''}">🔍 Solo Google Maps ({len([l for l in all_leads_pendientes if l.get('origen', '').startswith('GOOGLE')])})</a>
                <a href="/?filter_origin=manual" class="filter-btn {'active' if filter_origin == 'manual' else ''}">📁 Solo Manuales ({len([l for l in all_leads_pendientes if l.get('origen', '') == 'MANUAL_CSV'])})</a>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; background:#1E293B; padding:20px; border-radius:8px;">
                <div><strong>Enviados:</strong> <span style="color:#22C55E; font-size:1.5rem;">{leads_enviados}</span></div>
                <div><strong>Pendientes ({filter_label}):</strong> <span style="color:#F59E0B; font-size:1.5rem;">{len(leads_pendientes)}</span></div>
                <a href="/api/export-excel" class="btn-export">📥 Exportar Excel</a>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>#</th><th>Nombre</th><th>Negocio / Rubro</th><th>Distrito</th><th>WhatsApp</th><th>Plan Sugerido</th><th>Origen</th><th>Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
            
            <div style="margin-top:40px; text-align:center;">
                <p style="color:#64748B; font-size:0.9rem;">v8.0 • Búsqueda Inteligente • Exportación Excel • Historial • Filtros por Origen</p>
                <div style="margin-top:10px;">
                    <a href="/historial" style="color:#A78BFA; text-decoration:none;">📜 Ver Historial de Búsquedas</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)