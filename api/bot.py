# -*- coding: utf-8 -*-
"""Telegram Bot Handler - Main entry point for Vercel serverless function."""
import json
import traceback
import sys
import os
from http.server import BaseHTTPRequestHandler

# --- VERCEL PATH FIX ---
# Добавляем папку 'api' в sys.path, чтобы imports работали правильно
# Vercel запускает из корня (/var/task), а модули лежат в /var/task/api
current_dir = os.getcwd()
api_dir = os.path.join(current_dir, 'api')
if api_dir not in sys.path:
    sys.path.append(api_dir)

# --- Imports (Global Scope) ---
try:
    # --- Utils ---
    from utils.config import (
        validate_env_vars,
        ALLOWED_TELEGRAM_ID
    )
    # --- Services ---
    from services.telegram import (
        send_telegram_message
    )
    # --- Handlers ---
    from handlers.callbacks import handle_callback
    from handlers.commands import handle_command
    from handlers.messages import handle_message

    # Validate environment variables at startup
    validate_env_vars()

except Exception as e:
    # Критическая ошибка старта - выводим в лог Vercel
    print(f"[CRITICAL STARTUP ERROR] {e}", file=sys.stderr)
    traceback.print_exc()


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chat_id = None
        try:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            update = json.loads(body.decode('utf-8'))

            # --- ДЕДУПЛИКАЦИЯ ЗАПРОСОВ TELEGRAM (защита от infinite loop при таймаутах) ---
            update_id = update.get('update_id')
            if update_id:
                try:
                    from services.state import redis_client
                    dedup_key = f"dany:update:{update_id}"
                    if redis_client.get(dedup_key):
                        print(f"[DEDUPLICATION] Игнорируем повторный запрос Telegram с update_id {update_id}")
                        self.send_response(200)
                        self.end_headers()
                        return
                    redis_client.setex(dedup_key, 300, "1")
                except Exception as redis_err:
                    print(f"[DEDUPLICATION ERROR] {redis_err}")

            message = update.get('message')
            callback_query = update.get('callback_query')

            # --- ОБРАБОТКА НАЖАТИЯ КНОПОК ---
            if callback_query:
                callback_data = callback_query['data']
                chat_id = callback_query['message']['chat']['id']
                user_id = str(callback_query['from']['id'])
                callback_query_id = callback_query['id']

                # Валидация пользователя для callback_query
                allowed_id = ALLOWED_TELEGRAM_ID.strip() if ALLOWED_TELEGRAM_ID else ""
                if user_id != allowed_id:
                    self.send_response(200)
                    self.end_headers()
                    return

                handle_callback(chat_id, user_id, callback_query_id, callback_data, callback_query)
                
                self.send_response(200)
                self.end_headers()
                return

            # --- ОБРАБОТКА СООБЩЕНИЙ ---
            if not message:
                self.send_response(200)
                self.end_headers()
                return

            user_id = str(message['from']['id'])
            chat_id = message['chat']['id']

            # Валидация пользователя для сообщений
            allowed_id = ALLOWED_TELEGRAM_ID.strip() if ALLOWED_TELEGRAM_ID else ""
            if user_id != allowed_id:
                self.send_response(200)
                self.end_headers()
                return
            
            text = message.get('text', '')

            # 1. Сначала обрабатываем текстовые команды бота
            is_command_handled = handle_command(chat_id, user_id, text, message)
            if not is_command_handled:
                # 2. Если это не команда, обрабатываем как обычное сообщение (заметка, аудио и т.д.)
                handle_message(chat_id, user_id, text, message)
                
        except Exception as e:
            if chat_id:
                try:
                    err_msg = str(e)
                    err_msg_lower = err_msg.lower()
                    if "429" in err_msg_lower or "insufficient_quota" in err_msg_lower or "rate_limit" in err_msg_lower:
                        friendly_msg = (
                            "⚠️ <b>Превышена квота или лимит запросов OpenAI!</b>\n\n"
                            "Пожалуйста, проверьте статус оплаты и баланс вашего аккаунта OpenAI "
                            "в личном кабинете (раздел Billing).\n"
                            "Если баланс положительный, возможно, вы временно превысили лимит запросов в минуту (RPM/TPM)."
                        )
                        send_telegram_message(chat_id, friendly_msg, use_html=True)
                    elif "401" in err_msg_lower or "invalid_api_key" in err_msg_lower:
                        friendly_msg = (
                            "⚠️ <b>Ошибка авторизации OpenAI!</b>\n\n"
                            "Пожалуйста, проверьте правильность вашего API-ключа (OPENAI_API_KEY) в настройках проекта Vercel."
                        )
                        send_telegram_message(chat_id, friendly_msg, use_html=True)
                    else:
                        send_telegram_message(chat_id, f"🤯 *Произошла глобальная ошибка!*\nПожалуйста, проверьте логи Vercel.\n`{e}`")
                except Exception as tg_err:
                    print(f"Не удалось отправить TG-сообщение об ошибке: {tg_err}")
            print(f"Произошла глобальная ошибка: {e}")
            traceback.print_exc()
        
        self.send_response(200)
        self.end_headers()
        return
