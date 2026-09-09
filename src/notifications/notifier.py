import smtplib
from email.mime.text import MIMEText
class OrasicNotifier:
    def __init__(self, config):
        self.config = config
    async def send_email_alert(self, subject, body):
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.config.SMTP_EMAIL
            msg["To"] = self.config.NOTIFICATION_EMAIL
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(self.config.SMTP_EMAIL, self.config.SMTP_APP_PASSWORD)
                s.send_message(msg)
        except Exception as e:
            print(f"Email alert error: {e}")
