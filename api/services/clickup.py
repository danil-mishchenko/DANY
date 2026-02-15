# -*- coding: utf-8 -*-
"""Сервис для работы с ClickUp API."""
import requests
from datetime import datetime

from utils.config import CLICKUP_API_TOKEN, CLICKUP_TEAM_ID, CLICKUP_USER_ID, DEFAULT_TIMEOUT

CLICKUP_BASE_URL = "https://api.clickup.com/api/v2"

# Статусы которые НЕ показываем в списке задач
HIDDEN_STATUSES = {"на узгодження", "пауза проєкт", "пауза проект", "проеб"}

# Маппинг приоритетов на эмодзи
PRIORITY_EMOJI = {
    "urgent": "🔴",
    "high": "🟠",
    "normal": "🟡",
    "low": "🟢",
    "none": "⚪️"
}

# Маппинг статусов на эмодзи
STATUS_EMOJI = {
    "вхідні": "📥",
    "в роботі": "🔧",
    "на узгодження": "👀",
    "ресайзи": "📐",
    "to do": "📋",
    "in progress": "🔧",
    "open": "📥",
    "review": "👀",
    "complete": "✅",
    "closed": "✅"
}


def _headers():
    return {"Authorization": CLICKUP_API_TOKEN}


def get_my_tasks(include_closed=False) -> list:
    """Получает все задачи назначенные на пользователя.
    
    Returns:
        list: Список задач с полями name, status, priority, due_date, url
    """
    if not CLICKUP_API_TOKEN:
        return []
    
    url = f"{CLICKUP_BASE_URL}/team/{CLICKUP_TEAM_ID}/task"
    params = {
        "assignees[]": CLICKUP_USER_ID,
        "subtasks": "true",
        "include_closed": str(include_closed).lower(),
        "page": "0"
    }
    
    try:
        response = requests.get(url, headers=_headers(), params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        raw_tasks = response.json().get('tasks', [])
        
        tasks = []
        for t in raw_tasks:
            priority = t.get('priority')
            p_name = priority.get('priority', 'none') if priority else 'none'
            status_name = t.get('status', {}).get('status', '?')
            
            # Пропускаем скрытые статусы
            if status_name.lower() in HIDDEN_STATUSES:
                continue
            
            due_date = None
            if t.get('due_date'):
                try:
                    due_date = datetime.fromtimestamp(int(t['due_date']) / 1000)
                except (ValueError, TypeError):
                    pass
            
            # Извлекаем теги (бренды)
            tags = [tag.get('name', '') for tag in t.get('tags', [])]
            
            tasks.append({
                'name': t.get('name', ''),
                'status': t.get('status', {}).get('status', '?'),
                'priority': p_name,
                'due_date': due_date,
                'url': t.get('url', ''),
                'id': t.get('id', ''),
                'tags': tags
            })
        
        return tasks
    except Exception as e:
        print(f"ClickUp API error: {e}")
        return []


def _escape_markdown(text: str) -> str:
    """Экранирует спецсимволы Telegram Markdown."""
    for char in ['*', '_', '`', '[', ']', '(', ')']:
        text = text.replace(char, '')
    return text


def format_tasks_message(tasks: list, hidden_ids: list = None) -> str:
    """Форматирует список задач в красивое Telegram сообщение."""
    if hidden_ids:
        tasks = [t for t in tasks if t.get('id', '') not in hidden_ids]
    
    if not tasks:
        return "📋 *ClickUp*\n\nНет активных задач. Отлично! 🎉"
    
    # Сортируем: urgent → high → normal → low → none
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3, "none": 4}
    tasks.sort(key=lambda t: priority_order.get(t['priority'], 4))
    
    # Группируем по статусу
    by_status = {}
    for t in tasks:
        status = t['status']
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(t)
    
    lines = [f"📋 *ClickUp — Твои задачи ({len(tasks)})*"]
    
    for i, (status, status_tasks) in enumerate(by_status.items()):
        emoji = STATUS_EMOJI.get(status.lower(), "📌")
        safe_status = _escape_markdown(status.upper())
        
        if i > 0:
            lines.append("")
            lines.append("–––––––")
        
        lines.append("")
        lines.append(f"{emoji} *{safe_status}*")
        lines.append("")
        
        for t in status_tasks:
            p_emoji = PRIORITY_EMOJI.get(t['priority'], '⚪️')
            safe_name = _escape_markdown(t['name'])
            
            # Форматируем теги
            tags_str = ""
            if t.get('tags'):
                safe_tags = [_escape_markdown(tag) for tag in t['tags']]
                tags_str = f" *[{', '.join(safe_tags)}]*"
            
            # Форматируем дедлайн
            due_str = ""
            if t['due_date']:
                now = datetime.now()
                diff = (t['due_date'].date() - now.date()).days
                if diff < 0:
                    due_str = f" ⚠️ просрочено {abs(diff)} дн."
                elif diff == 0:
                    due_str = " 🔥 сегодня"
                elif diff == 1:
                    due_str = " ⏰ завтра"
                else:
                    due_str = f" 📅 {t['due_date'].strftime('%d.%m')}"
            
            lines.append(f"  {p_emoji}{tags_str} {safe_name}{due_str}")
            lines.append("")
    
    return "\n".join(lines)

