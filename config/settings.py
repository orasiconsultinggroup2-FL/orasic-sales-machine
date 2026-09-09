import os
from dotenv import load_dotenv
load_dotenv()
class Settings:
    COMPANY_NAME="ORASIC Lab"
    FOUNDER="Fernando Perez Roman"
    WEBSITE="https://orasic-sales-machine.onrender.com"
    GEMINI_API_KEY=os.getenv("GEMINI_API_KEY","")
    GROQ_API_KEY=os.getenv("GROQ_API_KEY","")
    SUPABASE_URL=os.getenv("SUPABASE_URL","")
    SUPABASE_KEY=os.getenv("SUPABASE_KEY","")
    GOOGLE_PLACES_API_KEY=os.getenv("GOOGLE_PLACES_API_KEY","")
    SMTP_EMAIL=os.getenv("SMTP_EMAIL","")
    SMTP_APP_PASSWORD=os.getenv("SMTP_APP_PASSWORD","")
    NOTIFICATION_EMAIL=os.getenv("NOTIFICATION_EMAIL","orasiclab@gmail.com")
    PORT=int(os.getenv("PORT",8000))
    SEARCH_INTERVAL=int(os.getenv("SEARCH_INTERVAL_MINUTES",30))
    AI_PROVIDER="gemini"
    GEMINI_MODEL="gemini-2.0-flash"
    GROQ_MODEL="llama-3.3-70b-versatile"
    AI_DAILY_LIMIT=200
    PLANS={"STARTER":{"name":"STARTER","price_oneshot":2497,"price_setup":599,"price_monthly":99,"dev_hours":"2-3h","support":"30min/mes","target":["freelancers","coaches","consultores"]},"MANAGER":{"name":"MANAGER","price_oneshot":4997,"price_setup":649,"price_monthly":149,"dev_hours":"5-6h","support":"1h/mes","target":["barberias","clinicas","spas","canchas","academias"]},"PRO":{"name":"PRO","price_oneshot":7997,"price_setup":699,"price_monthly":299,"dev_hours":"10-12h","support":"2-3h/mes","target":["gimnasios","red clinicas","agencias","multi-sede"]},"CUSTOM":{"name":"CUSTOM","price_min":10000,"dev_hours":"20-40h+","target":["inmobiliarias","distribuidoras","empresas grandes"]}}
    SEARCH_SOURCES={"google_maps":{"enabled":True,"categories":["barberia","clinica","gimnasio","restaurante","academia","veterinaria","spa"],"cities":["Lima","Arequipa","Trujillo","Bogota","Medellin","Santiago","CDMX","Madrid"]},"linkedin_jobs":{"enabled":True,"keywords":["transformacion digital","CRM","automatizacion","Sales Enablement","SDR"],"locations":["Peru","Colombia","Chile","Mexico","Espana"]},"google_alerts":{"enabled":True,"keywords":["necesito pagina web negocio","necesito sistema de reservas","automatizar mi negocio"]}}
    CLASSIFICATION={"STARTER":{"industries":["coach","consultor","freelance","disenador","fotografo"],"signals":["sin_web","negocio_pequeno"],"min_score":60},"MANAGER":{"industries":["barberia","clinica","veterinaria","cancha","spa","academia"],"signals":["reservas","citas","agenda"],"min_score":65},"PRO":{"industries":["gimnasio","red clinicas","agencia","franquicia"],"signals":["automatizacion","chatbot","multi sede"],"min_score":70},"CUSTOM":{"industries":["inmobiliaria","distribuidora","manufactura"],"signals":["erp","legacy","licitacion"],"min_score":75}}
    SCORING={"plan_fit":30,"industry_match":20,"pain_urgency":20,"budget_capacity":15,"digital_maturity":10,"recency":5}
    OUTREACH={"max_daily_emails":30,"follow_up_days":[0,2,5,10,15,45],"approval_above":5000}
    DAILY_LIMITS={"search_cycles":8,"leads_per_cycle":25,"


