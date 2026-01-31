# -*- coding: utf-8 -*-
"""Cron endpoint для отправки Telegram уведомлений о ближайших событиях."""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
import json
import os

# Lazy imports
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
GOOGLE_CALENDAR_ID = os.environ.get('GOOGLE_CALENDAR_ID')
ALLOWED_TELEGRAM_ID = os.environ.get('ALLOWED_TELEGRAM_ID')
USER_TIMEZONE = os.environ.get('USER_TIMEZONE', 'Europe/Kiev')


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Обработчик cron-запросов. Проверяет ближайшие события и отправляет уведомления."""
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            from services.telegram import send_telegram_message
            from services.notion import get_user_settings
            
            # Получаем настройки пользователя
            if not ALLOWED_TELEGRAM_ID:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "no user configured"}')
                return
            
            settings = get_user_settings(ALLOWED_TELEGRAM_ID)
            reminder_minutes = settings.get('reminder_minutes', 15)
            
            if reminder_minutes == 0:
                # Уведомления отключены
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "notifications disabled"}')
                return
            
            # Подключаемся к Google Calendar
            creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
            creds = service_account.Credentials.from_service_account_info(creds_info)
            service = build('calendar', 'v3', credentials=creds)
            
            # Ищем события в ближайшие reminder_minutes + 5 минут
            now = datetime.utcnow()
            time_min = now.isoformat() + 'Z'
            time_max = (now + timedelta(minutes=reminder_minutes + 5)).isoformat() + 'Z'
            
            events_result = service.events().list(
                calendarId=GOOGLE_CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            notifications_sent = 0
            
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                event_time = datetime.fromisoformat(start.replace('Z', '+00:00'))
                time_until_event = (event_time.replace(tzinfo=None) - now).total_seconds() / 60
                
                # Отправляем уведомление если событие через reminder_minutes (±2 минуты)
                if reminder_minutes - 2 <= time_until_event <= reminder_minutes + 2:
                    title = event.get('summary', 'Событие')
                    html_link = event.get('htmlLink', '')
                    
                    msg = f"🔔 *Напоминание!*\n\n📅 *{title}*\n⏰ Через {int(time_until_event)} мин"
                    
                    # Добавляем кнопку ссылки на событие
                    buttons = [[{"text": "📅 Открыть в календаре", "url": html_link}]] if html_link else None
                    
                    if buttons:
                        from services.telegram import send_message_with_buttons
                        send_message_with_buttons(int(ALLOWED_TELEGRAM_ID), msg, buttons)
                    else:
                        send_telegram_message(int(ALLOWED_TELEGRAM_ID), msg)
                    
                    notifications_sent += 1
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "notifications_sent": notifications_sent,
                "events_checked": len(events)
            }).encode())
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
