from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from supabase import create_client, Client
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = FastAPI()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key) if url and key else None

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "orasiclab@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

# --- LEADS HARD CODED (Muestra funcional + lógica de carga desde Supabase) ---
LEADS_DATA = [
    {"id": 1, "nombre": "Top Vision Barbershop", "rubro": "Barberías", "distrito": "Surco", "plan": "PRO", "pitch": "Asunto: operación diaria en Top Vision Barbershop\n\nHola, ¿cómo están? Les escribe Fernando.\n\nHe visto cómo ha crecido Top Vision Barbershop en Surco. Llegar a 544 reseñas no es nada fácil, felicidades por eso.\n\nJustamente por ese volumen, me imagino que llevar todo el día a día ya debe ser un reto. Vi por ahí en sus reseñas que han tenido algunos roces con: Sin quejas relevantes en la muestra.\n\nCuando un local llega a ese tamaño, el problema ya no es conseguir clientes, sino que la operación no se trague las ganancias. Cosas que pasan siempre en los Barberías grandes:\n\n1. Si tu mejor barbero se va mañana, se lleva la agenda de clientes en su propio celular y el local se queda en ceros. La base de datos tiene que ser del negocio, no del empleado.\n2. Los martes y miércoles las sillas están vacías (y el alquiler corre igual), mientras que los sábados hay tanta gente que se van porque no encuentran hora. Es plata que se escapa por no saber balancear la agenda.\n3. Depender de que el cliente 'se acuerde' de volver a los 20 días. Si nadie le manda un mensajito al día 18 recordándole que ya toca el retoque, esa venta se la lleva la barbería de la esquina.\n\nA este nivel, una simple agenda ya no sirve. Necesitan algo que trabaje para ustedes y tape esas fugas de dinero. Eso es lo que hacemos en ORASIC Lab para negocios con alto volumen.\n\n¿Tendrían 15 minutitos esta semana para mostrarles cómo quitamos ese peso operativo de encima? \n\nQuedo atento,\nFernando Perez\nORASIC Lab"},
    {"id": 2, "nombre": "Nápoles Barber Shop", "rubro": "Barberías", "distrito": "Surco", "plan": "STARTER", "pitch": "Asunto: duda sobre Nápoles Barber Shop en Maps\n\nHola, ¿qué tal? \n\nEstaba buscando un buen Barberías por Surco y me salió su local. Vi que tienen muy buenos comentarios (4.7 estrellas), así que se nota que le ponen empeño.\n\nPero me fijé en un detalle: Estacionamiento limitado.\n\nLes escribo porque justo trabajo ayudando a locales a arreglar estas cosas. Hoy en día pasa mucho que la gente busca en el celular y, si no pueden agendar o preguntar rápido en dos toques, se van al local de al lado que sí lo tiene fácil. \n\nY ojo, esto suele traer otros problemas que uno a veces ni nota:\n- Si tu mejor barbero se va mañana, se lleva la agenda de clientes en su propio celular y el local se queda en ceros. La base de datos tiene que ser del negocio, no del empleado.\n- Los martes y miércoles las sillas están vacías (y el alquiler corre igual), mientras que los sábados hay tanta gente que se van porque no encuentran hora. Es plata que se escapa por no saber balancear la agenda.\n- Depender de que el cliente 'se acuerde' de volver a los 20 días. Si nadie le manda un mensajito al día 18 recordándole que ya toca el retoque, esa venta se la lleva la barbería de la esquina.\n\nNosotros armamos algo súper rápido para que dejen de perder esos clientes y tapen esas fugas. \n\nSi les da curiosidad ver cómo quedaría, respóndanme este correo y les paso un ejemplo de un minuto. Cero compromiso.\n\nUn saludo,\nFernando Perez \nORASIC Lab"}
]

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    leads = []
    if supabase:
        try:
            response = supabase.table("leads").select("*").eq("estado", "Pendiente").order("id", desc=False).execute()
            leads = response.data
        except: pass
    
    if not leads:
        leads = LEADS_DATA

    rows_html = ""
    for lead in leads:
        p = lead.get('pitch_generado') or lead.get('pitch', '')
        pitch_safe = p.replace("'", "\\'").replace("\n", "\\n").replace('"', '\\"')
        plan = lead.get('plan_sugerido') or lead.get('plan', 'STARTER')
        rows_html += f'''
        <tr>
            <td><strong>{lead.get('nombre', 'N/A')}</strong></td>
            <td>{lead.get('rubro', 'N/A')}<br><small>{lead.get('distrito', 'N/A')}</small></td>
            <td><span class="badge badge-{plan.lower()}">{plan}</span></td>
            <td><button onclick="alert(\"{pitch_safe}\")">👁️ Ver Pitch</button></td>
            <td style="text-align:center;"><input type="checkbox" name="lead_ids" value="{lead.get('id', 0)}" checked></td>
        </tr>'''

    return f'''<!DOCTYPE html><html><head><title>ORASIC Sales Machine</title>
    <style>body{{font-family:sans-serif;background:#f8f9fa;padding:20px;}}.container{{max-width:1200px;margin:0 auto;background:white;padding:30px;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,0.1);}}table{{width:100%;border-collapse:collapse;margin-top:20px;}}th,td{{padding:12px;border-bottom:1px solid #ddd;text-align:left;}}th{{background:#343a40;color:white;}}.badge{{padding:4px 8px;border-radius:4px;color:white;font-size:0.85em;font-weight:bold;}}.badge-starter{{background:#28a745;}}.badge-manager{{background:#007bff;}}.badge-pro{{background:#6f42c1;}}.badge-custom{{background:#fd7e14;}}button{{background:#6c757d;color:white;border:none;padding:6px 12px;cursor:pointer;border-radius:4px;}}#disparar-btn{{background:#dc3545;color:white;padding:15px 30px;font-size:1.1em;border:none;border-radius:5px;cursor:pointer;font-weight:bold;float:right;margin-top:20px;}}</style>
    </head><body><div class="container"><h1>🚀 ORASIC Lab Sales Machine v1.0</h1><p>Leads listos: <strong>{len(leads)}</strong></p>
    <form action="/disparar" method="post"><table><thead><tr><th>Negocio</th><th>Rubro / Distrito</th><th>Plan</th><th>Pitch</th><th style="text-align:center;">Enviar</th></tr></thead><tbody>{rows_html}</tbody></table>
    <button type="submit" id="disparar-btn">🔥 DISPARAR CAMPAÑA SELECCIONADA</button></form></div></body></html>'''

@app.post("/disparar")
async def disparar_campana(request: Request):
    form_data = await request.form()
    lead_ids = form_data.getlist("lead_ids")
    if not lead_ids: return HTMLResponse(content="<h2>⚠️ No seleccionaste ningún lead.</h2><a href='/'>Volver</a>")
    
    enviados = 0
    for lid in lead_ids:
        try:
            lead_data = next((x for x in LEADS_DATA if str(x.get('id')) == str(lid)), None)
            if not lead_data and supabase:
                res = supabase.table("leads").select("*").eq("id", int(lid)).execute()
                if res.data: lead_data = res.data[0]
            
            if lead_data:
                msg = MIMEMultipart()
                msg['From'] = SMTP_EMAIL
                msg['To'] = SMTP_EMAIL
                msg['Subject'] = f"[PRUEBA ORASIC] Pitch para: {lead_data.get('nombre', 'Lead')}"
                msg.attach(MIMEText(lead_data.get('pitch_generado') or lead_data.get('pitch', ''), 'plain', 'utf-8'))
                if SMTP_PASSWORD:
                    with smtplib.SMTP('smtp.gmail.com', 587) as server:
                        server.starttls()
                        server.login(SMTP_EMAIL, SMTP_PASSWORD)
                        server.send_message(msg)
                enviados += 1
                if supabase and isinstance(lead_data.get('id'), int):
                    try: supabase.table("leads").update({"estado": "Enviado"}).eq("id", lead_data['id']).execute()
                    except: pass
        except Exception as e: print(f"Error: {e}")
            
    return HTMLResponse(content=f"<div style='font-family:sans-serif;padding:20px;'><h2>✅ Campaña procesada.</h2><p>Correos enviados a tu bandeja ({SMTP_EMAIL}): <strong>{enviados}</strong></p><a href='/' style='color:blue;'>Volver al Dashboard</a></div>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
