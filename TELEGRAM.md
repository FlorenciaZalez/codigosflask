# Avisos de códigos por Telegram

Se envía un mensaje cuando una entrega web o reserva de TibaDigital deja exactamente 1 código disponible para una cuenta. No se envía de nuevo al bajar a 0; una nueva recarga permite avisar otra vez al llegar a 1. Las cuentas que ya tienen 1 código no generan un aviso retroactivo.

1. En Telegram, abrí https://t.me/BotFather, enviá `/newbot` y seguí las instrucciones para obtener el token.
2. Abrí el chat con tu nuevo bot y enviá `/start`.
3. Consultá `getUpdates` de la API de Telegram con ese token y buscá el campo `message.chat.id` de tu mensaje.
4. Configurá en el servidor o en el `.env` de la app activa:

   ```env
   TELEGRAM_BOT_TOKEN=token_del_bot
   TELEGRAM_CHAT_ID=id_del_chat
   ```

5. Reiniciá la aplicación.

El token debe guardarse en la configuración privada, nunca en el repositorio. La integración usa HTTPS y requiere acceso del hosting a `api.telegram.org`. Si faltan variables, no se intenta enviar. Un error de Telegram se registra sin incluir el token y no cancela la entrega del código. Actualmente no hay reintentos automáticos de avisos fallidos.

La integración está en `codigo_app/app.py` (Render/Procfile) y `codigo_app/codigo_app/app.py` (wsgi.py).

Documentación: https://core.telegram.org/bots/tutorial y https://core.telegram.org/bots/api#getupdates
