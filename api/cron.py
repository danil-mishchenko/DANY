# -*- coding: utf-8 -*-
"""Cron endpoint для отправки Telegram уведомлений о ближайших событиях."""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
import json
import os
import traceback

GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
GOOGLE_CALENDAR_ID = os.environ.get('GOOGLE_CALENDAR_ID')
ALLOWED_TELEGRAM_ID = os.environ.get('ALLOWED_TELEGRAM_ID')
USER_TIMEZONE = os.environ.get('USER_TIMEZONE', 'Europe/Kiev')


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Обработчик cron-запросов. Проверяет ближайшие события и отправляет уведомления."""
        result = {"status": "unknown"}
        try:
            import pytz
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            from services.telegram import send_telegram_message, send_message_with_buttons
            from services.notion import get_user_settings
            
            if not ALLOWED_TELEGRAM_ID:
                result = {"status": "no user configured"}
                self._respond(200, result)
                return
            
            if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_CALENDAR_ID:
                result = {"status": "no google credentials"}
                self._respond(200, result)
                return
            
            # Получаем настройки
            settings = get_user_settings(ALLOWED_TELEGRAM_ID)
            reminder_minutes = settings.get('reminder_minutes', 15)
            
            if reminder_minutes == 0:
                result = {"status": "notifications disabled"}
                self._respond(200, result)
                return
            
            # Подключаемся к Google Calendar
            creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
            creds = service_account.Credentials.from_service_account_info(creds_info)
            service = build('calendar', 'v3', credentials=creds)
            
            # Текущее время в UTC
            now_utc = datetime.utcnow()
            # Окно поиска: от сейчас до reminder_minutes + 3 минуты вперёд
            time_min = now_utc.isoformat() + 'Z'
            time_max = (now_utc + timedelta(minutes=reminder_minutes + 3)).isoformat() + 'Z'
            
            events_result = service.events().list(
                calendarId=GOOGLE_CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            notifications_sent = 0
            
            tz = pytz.timezone(USER_TIMEZONE)
            now_local = datetime.now(tz)
            
            for event in events:
                start_str = event['start'].get('dateTime', event['start'].get('date'))
                
                # Пропускаем целодневные события (без времени)
                if 'T' not in start_str:
                    continue
                
                try:
                    # Парсим время события
                    from dateutil import parser as dateutil_parser
                    event_time = dateutil_parser.parse(start_str)
                except Exception:
                    # Фоллбэк: ручной парсинг
                    try:
                        # Формат: 2026-02-13T18:00:00+02:00
                        event_time = datetime.fromisoformat(start_str)
                    except Exception:
                        continue
                
                # Приводим к timezone пользователя
                if event_time.tzinfo is None:
                    event_time = tz.localize(event_time)
                
                # Считаем минуты до события
                time_until = (event_time - now_local).total_seconds() / 60
                
                # Отправляем если событие попадает в окно (reminder_minutes ± 3 мин)
                if reminder_minutes - 3 <= time_until <= reminder_minutes + 3:
                    title = event.get('summary', 'Событие')
                    html_link = event.get('htmlLink', '')
                    event_time_str = event_time.strftime('%H:%M')
                    
                    msg = f"🔔 *Напоминание!*\n\n📅 *{title}*\n⏰ В {event_time_str} (через {int(time_until)} мин)"
                    
                    if html_link:
                        buttons = [[{"text": "📅 Открыть в календаре", "url": html_link}]]
                        send_message_with_buttons(int(ALLOWED_TELEGRAM_ID), msg, buttons)
                    else:
                        send_telegram_message(int(ALLOWED_TELEGRAM_ID), msg)
                    
                    notifications_sent += 1
            
            result = {
                "status": "ok",
                "notifications_sent": notifications_sent,
                "events_checked": len(events),
                "reminder_minutes": reminder_minutes,
                "server_time_utc": now_utc.strftime('%H:%M:%S'),
                "user_time": now_local.strftime('%H:%M:%S')
            }
            self._respond(200, result)
            
        except Exception as e:
            error_detail = traceback.format_exc()
            print(f"CRON ERROR: {error_detail}")
            result = {"error": str(e), "traceback": error_detail}
            self._respond(500, result)
    
    def _respond(self, code, data):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
