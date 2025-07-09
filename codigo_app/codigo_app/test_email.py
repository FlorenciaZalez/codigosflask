import os
import smtplib
from dotenv import load_dotenv
from email.message import EmailMessage

# Cargar variables del .env
load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

msg = EmailMessage()
msg['Subject'] = "🧪 Prueba de envío"
msg['From'] = EMAIL_ADDRESS
msg['To'] = "tibadigitalcodigos@gmail.com"  # Cambiá si querés otro destino
msg.set_content("Este es un correo de prueba desde Flask 🧪")

try:
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.send_message(msg)
    print("✅ Correo enviado correctamente.")
except Exception as e:
    print("❌ Error al enviar el correo:", e)