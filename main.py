from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from datetime import datetime
app = FastAPI(title="ORASIC Lab Sales Machine", version="1.0.0")
@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.now().isoformat()}
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return "<h1>ORASIC Lab Sales Machine v1.0</h1><p>Running</p>"
