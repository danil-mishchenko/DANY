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

# XP за приоритет
XP_PER_PRIORITY = {"urgent": 50, "high": 30, "normal": 15, "low": 10, "none": 5}


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
                self._award_xp(task_id)
                break
    
    def _award_xp(self, task_id: str):
        """Начисляет XP за закрытую задачу."""
        try:
            from services.clickup import get_my_tasks
            from services.notion import get_user_xp, set_user_xp
            from services.telegram import send_telegram_message
            
            if not ALLOWED_TELEGRAM_ID:
                return
            
            # Получаем инфо о задаче через API для приоритета
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
            priority = task_data.get('priority', {})
            p_name = priority.get('priority', 'none') if priority else 'none'
            tags = [tag.get('name', '') for tag in task_data.get('tags', [])]
            
            # Считаем XP
            xp_gained = XP_PER_PRIORITY.get(p_name, 5)
            
            # Получаем текущий XP
            xp_data = get_user_xp(ALLOWED_TELEGRAM_ID)
            old_xp = xp_data.get('xp', 0)
            new_xp = old_xp + xp_gained
            
            # RPG уровни
            from services.briefing import get_rpg_level
            old_title, _ = get_rpg_level(old_xp)
            new_title, next_threshold = get_rpg_level(new_xp)
            
            # Сохраняем
            xp_data['xp'] = new_xp
            set_user_xp(ALLOWED_TELEGRAM_ID, xp_data)
            
            # Формируем уведомление
            tags_str = f" [{', '.join(tags)}]" if tags else ""
            
            lines = []
            lines.append(f"<b>⚔️ +{xp_gained} XP!</b>")
            lines.append(f"✅{tags_str} {task_name}")
            lines.append("")
            
            if old_title != new_title:
                # LEVEL UP!
                lines.append(f"🎉🎉🎉 <b>LEVEL UP!</b>")
                lines.append(f"{old_title} → <b>{new_title}</b>")
                lines.append("")
            
            lines.append(f"{new_title}  •  <b>{new_xp} XP</b>")
            if next_threshold:
                remaining = next_threshold - new_xp
                lines.append(f"До следующего уровня: {remaining} XP")
            
            msg = "\n".join(lines)
            send_telegram_message(int(ALLOWED_TELEGRAM_ID), msg, use_html=True)
            
            print(f"XP awarded: +{xp_gained} for task '{task_name}' (total: {new_xp})")
            
        except Exception as e:
            import traceback
            print(f"XP award error: {traceback.format_exc()}")
    
    def _respond(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
