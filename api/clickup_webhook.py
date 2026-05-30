# -*- coding: utf-8 -*-
"""ClickUp Webhook endpoint — начисляет XP за закрытые задачи."""
import sys
import os
import json
from http.server import BaseHTTPRequestHandler

# --- VERCEL PATH FIX ---
current_dir = os.getcwd()
api_dir = os.path.join(current_dir, 'api')
if api_dir not in sys.path:
    sys.path.append(api_dir)

ALLOWED_TELEGRAM_ID = os.environ.get('ALLOWED_TELEGRAM_ID', '')

# Статусы, которые считаются "закрытыми"
CLOSED_STATUSES = {'complete', 'closed', 'done', 'завершено', 'готово', 'виконано'}




class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        """Обрабатывает webhook от ClickUp."""
        result = {"status": "ok"}
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            
            event = data.get('event', '')
            
            # ClickUp шлёт GET для верификации webhook
            # и POST для событий
            
            if event == 'taskStatusUpdated':
                self._handle_status_update(data)
            
            self._respond(200, result)
            
        except Exception as e:
            import traceback
            print(f"WEBHOOK ERROR: {traceback.format_exc()}")
            self._respond(200, {"status": "error", "detail": str(e)})
    
    def do_GET(self):
        """ClickUp верификация webhook endpoint."""
        self._respond(200, {"status": "ok"})
    
    def _handle_status_update(self, data):
        """Обрабатывает смену статуса задачи."""
        task_id = data.get('task_id', '')
        history_items = data.get('history_items', [])
        
        for item in history_items:
            if item.get('field') != 'status':
                continue
            
            after_status = item.get('after', {}).get('status', '').lower()
            before_status = item.get('before', {}).get('status', '').lower()
            
            # Проверяем: новый статус = закрыт, старый != закрыт
            if after_status in CLOSED_STATUSES and before_status not in CLOSED_STATUSES:
                self._notify_task_completed(task_id)
                break
    
    def _notify_task_completed(self, task_id: str):
        """Отправляет уведомление о закрытой задаче в Telegram."""
        try:
            from services.telegram import send_telegram_message
            
            if not ALLOWED_TELEGRAM_ID:
                return
            
            # Получаем инфо о задаче через API
            import requests
            clickup_token = os.environ.get('CLICKUP_API_TOKEN', '')
            if not clickup_token:
                return
            
            headers = {"Authorization": clickup_token}
            resp = requests.get(
                f"https://api.clickup.com/api/v2/task/{task_id}",
                headers=headers,
                timeout=10
            )
            
            if resp.status_code != 200:
                print(f"Failed to get task {task_id}: {resp.status_code}")
                return
            
            task_data = resp.json()
            task_name = task_data.get('name', 'Задача')
            tags = [tag.get('name', '') for tag in task_data.get('tags', [])]
            
            # Формируем уведомление
            tags_str = f" [{', '.join(tags)}]" if tags else ""
            
            msg = f"✅ <b>Задача выполнена!</b>\n\n{tags_str} {task_name}"
            send_telegram_message(int(ALLOWED_TELEGRAM_ID), msg, use_html=True)
            
            print(f"Task completed notification sent for: '{task_name}'")
            
        except Exception as e:
            import traceback
            print(f"Task notification error: {traceback.format_exc()}")
    
    def _respond(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
