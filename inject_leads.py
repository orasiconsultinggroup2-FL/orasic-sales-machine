import os
import pandas as pd
from supabase import create_client, Client

# Configuración
url = "https://ogdqznzanriisulxcqrz.supabase.co"
key = "sb_publishable_3LqmCkdBPjfMsq-Qnurjiw_ezLgTf5l"
if not key:
    print("❌ ERROR: No se encontró SUPABASE_KEY. Asegúrate de tenerla en tu .env o ponla manual aquí.")
    exit()

supabase: Client = create_client(url, key)

try:
    df = pd.read_csv("leads_con_pitches_humanos.csv")
    data_to_insert = []
    
    for index, row in df.iterrows():
        data_to_insert.append({
            "nombre": row["Nombre"],
            "rubro": row["Rubro"],
            "distrito": row["Distrito"],
            "plan_sugerido": row["Plan"],
            "pitch_generado": row["Pitch_Generado"],
            "estado": "Pendiente"
        })

    # Subir en lotes de 50
    total = len(data_to_insert)
    for i in range(0, total, 50):
        batch = data_to_insert[i:i+50]
        response = supabase.table("leads").insert(batch).execute()
        print(f"✅ Subidos {len(response.data)} leads... ({i+len(response.data)}/{total})")

    print("\n🎉 ¡Todos los leads inyectados en Supabase correctamente!")
except Exception as e:
    print(f"❌ Error durante la inyección: {e}")
