# -*- coding: utf-8 -*-
"""Сервис утреннего брифинга — собирает данные из Calendar, ClickUp и AI."""
import json
import requests
from datetime import datetime, timedelta

from utils.config import (
    GOOGLE_CREDENTIALS_JSON, GOOGLE_CALENDAR_ID, 
    USER_TIMEZONE, OPENAI_API_KEY, DEFAULT_TIMEOUT
)
from services.clickup import get_my_tasks, _escape_markdown, PRIORITY_EMOJI


def get_today_events() -> list:
    """Получает события из Google Calendar на сегодня."""
    if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_CALENDAR_ID:
        return []
    
    try:
        import pytz
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        service = build('calendar', 'v3', credentials=creds)
        
        tz = pytz.timezone(USER_TIMEZONE)
        now = datetime.now(tz)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = []
        for e in events_result.get('items', []):
            start_str = e['start'].get('dateTime', e['start'].get('date'))
            title = e.get('summary', 'Без названия')
            
            time_str = ""
            if 'T' in start_str:
                try:
                    from dateutil import parser as dp
                    event_time = dp.parse(start_str)
                    time_str = event_time.strftime('%H:%M')
                except Exception:
                    pass
            
            events.append({'title': title, 'time': time_str})
        
        return events
    except Exception as e:
        print(f"Briefing calendar error: {e}")
        return []


def get_urgent_tasks() -> list:
    """Получает самые горящие задачи (дедлайн сегодня или просрочен)."""
    all_tasks = get_my_tasks()
    now = datetime.now()
    
    urgent = []
    for t in all_tasks:
        if t['due_date']:
            diff = (t['due_date'].date() - now.date()).days
            if diff <= 0:  # Сегодня или просрочено
                t['_urgency'] = diff
                urgent.append(t)
    
    # Сортируем: самые просроченные первые
    urgent.sort(key=lambda t: t['_urgency'])
    return urgent[:5]


def generate_personal_insight(tasks: list, events: list) -> str:
    """Генерирует персонализированный инсайт на основе задач и событий."""
    if not OPENAI_API_KEY:
        return "Сделай сегодня то, что приблизит тебя к цели. Каждый шаг считается."
    
    # Собираем контекст
    tasks_context = "\n".join([
        f"- {t['name']} (бренд: {', '.join(t.get('tags', []))}, приоритет: {t['priority']}, "
        f"{'просрочено' if t.get('_urgency', 0) < 0 else 'дедлайн сегодня'})"
        for t in tasks
    ]) or "Нет горящих задач."
    
    events_context = "\n".join([
        f"- {e['time']} {e['title']}" for e in events
    ]) or "Нет событий."
    
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
        
        prompt = f"""Ты — персональный энергичный ассистент Данила, специалиста по digital-маркетингу и дизайну.

Вот его план на сегодня:

ЗАДАЧИ (ClickUp):
{tasks_context}

СОБЫТИЯ (Календарь):
{events_context}

Напиши персонализированный мотивационный инсайт на 2-3 предложения (максимум 200 символов).
Правила:
- Упомяни конкретные задачи или бренды из списка
- Дай практический совет как лучше организовать день
- Тон: энергичный, дружелюбный, как лучший друг-коуч
- Пиши на русском
- НЕ используй кавычки, НЕ начинай с "Утро" или "Доброе утро"
- НЕ используй символы Markdown (* _ ` [ ])"""
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 150,
            "temperature": 0.9
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        insight = response.json()['choices'][0]['message']['content'].strip()
        
        # Чистим от Markdown символов
        return _escape_markdown(insight)
    except Exception as e:
        print(f"Briefing AI error: {e}")
        return "Фокус на главном, остальное подождёт. Ты справишься!"


def build_morning_briefing() -> str:
    """Собирает полное сообщение утреннего брифинга."""
    import pytz
    tz = pytz.timezone(USER_TIMEZONE)
    now = datetime.now(tz)
    
    # Данные
    events = get_today_events()
    all_tasks = get_my_tasks()
    urgent_tasks = get_urgent_tasks()
    
    # === HEADER ===
    weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    day_name = weekdays[now.weekday()]
    date_str = now.strftime('%d.%m.%Y')
    
    lines = [f"🌅 *Погнали, Данил!*\n_{day_name}, {date_str}_\n"]
    
    # === CALENDAR ===
    if events:
        lines.append(f"📅 *Сегодня в расписании:*\n")
        for e in events:
            time_prefix = f"🕒 *{e['time']}*" if e['time'] else "📌"
            safe_title = _escape_markdown(e['title'])
            lines.append(f"{time_prefix} — {safe_title}")
        lines.append("")
    else:
        lines.append("📅 *Расписание чистое* — свободный день для фокуса!\n")
    
    lines.append("———")
    
    # === URGENT FOCUS ===
    if urgent_tasks:
        lines.append(f"\n🔥 *Горящие миссии ({len(urgent_tasks)}):*\n")
        for t in urgent_tasks:
            p_emoji = PRIORITY_EMOJI.get(t['priority'], '⚪️')
            safe_name = _escape_markdown(t['name'])
            
            tags_str = ""
            if t.get('tags'):
                safe_tags = [_escape_markdown(tag) for tag in t['tags']]
                tags_str = f" *[{', '.join(safe_tags)}]*"
            
            overdue = t.get('_urgency', 0) < 0
            marker = "⚠️ просрочено!" if overdue else "🔥 сегодня"
            
            lines.append(f"{p_emoji}{tags_str} {safe_name}")
            lines.append(f"   {marker}")
        lines.append("")
    
    # === ALL TASKS SUMMARY ===
    remaining = len(all_tasks) - len(urgent_tasks)
    if remaining > 0:
        lines.append(f"📋 И ещё *{remaining}* задач в работе.\n")
    
    lines.append("———")
    
    # === AI INSIGHT ===
    insight = generate_personal_insight(urgent_tasks or all_tasks[:5], events)
    lines.append(f"\n💡 *Инсайт дня:*\n{insight}\n")
    
    lines.append("🚀 *Зажги сегодня!*")
    
    return "\n".join(lines)
