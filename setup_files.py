import os
B = r'C:\Users\FERNANDO\ORASIC LAB\orasic-sales-machine'
files = {
    'main.py': 'from fastapi import FastAPI\nfrom fastapi.responses import HTMLResponse\nfrom datetime import datetime\napp = FastAPI(title="ORASIC Lab Sales Machine", version="1.0.0")\n@app.get("/health")\ndef health():\n    return {"status": "ok", "ts": datetime.now().isoformat()}\n@app.get("/", response_class=HTMLResponse)\ndef dashboard():\n    return "<h1>ORASIC Lab Sales Machine v1.0</h1><p>Running</p>"\n',
    'worker.py': 'import asyncio\nasync def worker_loop():\n    while True:\n        print("Worker running")\n        await asyncio.sleep(1800)\nif __name__ == "__main__":\n    asyncio.run(worker_loop())\n',
    'src/search/search_engine.py': 'class OrasicSearchEngine:\n    def __init__(self, config):\n        self.config = config\n',
    'src/classifier/lead_classifier.py': 'class OrasicLeadClassifier:\n    def __init__(self, config):\n        self.config = config\n',
    'src/pitch/pitch_generator.py': 'class OrasicPitchGenerator:\n    def __init__(self, config):\n        self.config = config\n',
    'src/production/production_engine.py': 'class OrasicProductionEngine:\n    def __init__(self, config):\n        self.config = config\n',
    'src/notifications/notifier.py': 'import smtplib\nfrom email.mime.text import MIMEText\nclass OrasicNotifier:\n    def __init__(self, config):\n        self.config = config\n    async def send_email_alert(self, subject, body):\n        try:\n            msg = MIMEText(body)\n            msg["Subject"] = subject\n            msg["From"] = self.config.SMTP_EMAIL\n            msg["To"] = self.config.NOTIFICATION_EMAIL\n            with smtplib.SMTP("smtp.gmail.com", 587) as s:\n                s.starttls()\n                s.login(self.config.SMTP_EMAIL, self.config.SMTP_APP_PASSWORD)\n                s.send_message(msg)\n        except Exception as e:\n            print(f"Email alert error: {e}")\n',
    'src/dashboard/app.py': 'DASHBOARD_HTML = "<h1>ORASIC Lab Sales Machine</h1>"\n'
}
for k, v in files.items():
    path = os.path.join(B, k)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(v)
print('Modulos creados OK')
