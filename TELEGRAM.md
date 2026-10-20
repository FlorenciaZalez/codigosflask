# Avisos de códigos por Telegram

Se envía un mensaje cuando una entrega web o reserva de TibaDigital deja 0 códigos disponibles para una cuenta. No se avisa cuando queda 1 código ni al intentar pedir códigos de una cuenta vacía. Una nueva recarga permite avisar otra vez cuando se agotan. Las cuentas que ya están vacías no generan un aviso retroactivo.

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
