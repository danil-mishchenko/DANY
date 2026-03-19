# -*- coding: utf-8 -*-
"""Сервис утреннего и вечернего брифинга."""
import json
import requests
from datetime import datetime, timedelta

from utils.config import (
    GOOGLE_CREDENTIALS_JSON, GOOGLE_CALENDAR_ID,
    USER_TIMEZONE, OPENAI_API_KEY, DEFAULT_TIMEOUT,
    NOTION_TOKEN, NOTION_DATABASE_ID, ALLOWED_TELEGRAM_ID
)
from services.clickup import get_my_tasks, _escape_markdown, PRIORITY_EMOJI
from services.notion import get_hidden_tasks, get_user_xp, set_user_xp


# === RPG XP СИСТЕМА ===
XP_PER_PRIORITY = {"urgent": 50, "high": 30, "normal": 15, "low": 10, "none": 5}

RPG_LEVELS = [
    (0, "🐀 Крестьянин"),
    (50, "🗡️ Оруженосец"),
    (150, "⚔️ Пехотинец"),
    (300, "🏹 Лучник"),
    (500, "🛡️ Рыцарь"),
    (750, "⚜️ Паладин"),
    (1050, "🐴 Конный Рыцарь"),
    (1400, "🏰 Комендант Крепости"),
    (1800, "🦁 Рыцарь Ордена"),
    (2300, "📜 Магистр"),
    (2900, "🗺️ Полководец"),
    (3600, "👑 Барон"),
    (4400, "🏛️ Граф"),
    (5300, "🦅 Герцог"),
    (6300, "⚔️👑 Великий Герцог"),
    (7500, "🔱 Принц"),
    (9000, "👸 Регент"),
    (11000, "🏰👑 Король"),
    (13500, "🌟 Император"),
    (16500, "🐉 Легенда"),
]


def get_rpg_level(xp: int) -> tuple:
    """Возвращает (название уровня, xp до следующего)."""
    current_level = RPG_LEVELS[0]
    next_threshold = RPG_LEVELS[1][0] if len(RPG_LEVELS) > 1 else None
    
    for i, (threshold, name) in enumerate(RPG_LEVELS):
        if xp >= threshold:
            current_level = (threshold, name)
            next_threshold = RPG_LEVELS[i + 1][0] if i + 1 < len(RPG_LEVELS) else None
        else:
            break
    
    return current_level[1], next_threshold


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


def get_last_notion_note() -> str:
    """Получает последнюю заметку из Notion для контекста."""
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        return ""

    try:
        url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
        payload = {
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
            "page_size": 1
        }
        headers = {
            'Authorization': f'Bearer {NOTION_TOKEN}',
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28'
        }
        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        results = response.json().get('results', [])
        if results:
            page = results[0]
            props = page.get('properties', {})
            for prop in props.values():
                if prop.get('type') == 'title':
                    title_arr = prop.get('title', [])
                    if title_arr:
                        return _escape_markdown(title_arr[0].get('plain_text', ''))
        return ""
    except Exception as e:
        print(f"Briefing Notion error: {e}")
        return ""


def get_urgent_tasks(hidden_ids: list = None) -> list:
    """Получает задачи с дедлайном сегодня или просрочено."""
    all_tasks = get_my_tasks()
    if hidden_ids:
        all_tasks = [t for t in all_tasks if t.get('id', '') not in hidden_ids]
    now = datetime.now()

    urgent = []
    for t in all_tasks:
        if t['due_date']:
            diff = (t['due_date'].date() - now.date()).days
            if diff <= 0:
                t['_urgency'] = diff
                urgent.append(t)

    urgent.sort(key=lambda t: t['_urgency'])
    return urgent[:5]


def generate_personal_insight(tasks: list, events: list) -> str:
    """Генерирует персонализированный инсайт."""
    if not OPENAI_API_KEY:
        return "Фокус на главном, остальное подождёт. Ты справишься!"

    tasks_context = "\n".join([
        f"- {t['name']} (бренд: {', '.join(t.get('tags', []))}, приоритет: {t['priority']}, "
        f"{'просрочено ' + str(abs(t.get('_urgency', 0))) + ' дн.' if t.get('_urgency', 0) < 0 else 'дедлайн сегодня'})"
        for t in tasks
    ]) or "Нет горящих задач."

    events_context = "\n".join([
        f"- {e['time']} {e['title']}" for e in events
    ]) or "Нет событий."

    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}

        prompt = f"""Ты — персональный энергичный ассистент по имени DANY. Обращайся к пользователю "Шеф".
Он — специалист по digital-маркетингу и дизайну.

Вот его план на сегодня:

ЗАДАЧИ (ClickUp):
{tasks_context}

СОБЫТИЯ (Календарь):
{events_context}

Напиши персонализированный мотивационный инсайт на 2-3 предложения.
Правила:
- Упомяни конкретные задачи или бренды из списка
- Дай практический совет как лучше организовать именно ЭТОТ день
- Тон: энергичный, дружелюбный, как лучший друг-коуч
- Пиши на русском
- НЕ используй кавычки вокруг текста, НЕ начинай с "Доброе утро"
- НЕ используй символы Markdown (* _ ` [ ] ( ))
- НЕ используй HTML теги"""

        payload = {
            "model": "gpt-5.4-nano",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.9
        }

        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        insight = response.json()['choices'][0]['message']['content'].strip()
        return _escape_markdown(insight)
    except Exception as e:
        print(f"Briefing AI error: {e}")
        return "Фокус на главном, остальное подождёт. Ты справишься!"


def build_morning_briefing() -> str:
    """Собирает полное сообщение утреннего брифинга (HTML формат)."""
    import pytz
    tz = pytz.timezone(USER_TIMEZONE)
    now = datetime.now(tz)

    # Данные
    user_id = ALLOWED_TELEGRAM_ID or ""
    hidden_ids = get_hidden_tasks(user_id) if user_id else []
    events = get_today_events()
    all_tasks = get_my_tasks()
    if hidden_ids:
        all_tasks = [t for t in all_tasks if t.get('id', '') not in hidden_ids]
    urgent_tasks = get_urgent_tasks(hidden_ids)
    last_note = get_last_notion_note()

    # XP
    xp_data = get_user_xp(user_id) if user_id else {'xp': 0, 'level': 1}
    current_xp = xp_data.get('xp', 0)
    rpg_title, next_threshold = get_rpg_level(current_xp)

    # Header
    weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    day_name = weekdays[now.weekday()]
    date_str = now.strftime('%d.%m.%Y')
    day_of_year = now.timetuple().tm_yday

    lines = []
    lines.append(f"<b>🌅 Погнали, Шеф!</b>")
    lines.append(f"<i>{day_name}, {date_str}  •  День #{day_of_year}</i>")
    xp_line = f"<i>{rpg_title}  •  {current_xp} XP</i>"
    if next_threshold:
        xp_line += f" <i>(до след: {next_threshold - current_xp})</i>"
    lines.append(xp_line)
    lines.append("")

    # КАЛЕНДАРЬ
    if events:
        lines.append(f"<b>📅 Сегодня в расписании:</b>")
        lines.append("")
        for e in events:
            time_prefix = f"🕒 <b>{e['time']}</b>" if e['time'] else "📌"
            lines.append(f"{time_prefix} — {e['title']}")
            lines.append("")
    else:
        lines.append("<b>📅 Расписание чистое</b> — свободный день для фокуса!")
        lines.append("")

    lines.append("–––––––")

    # ГОРЯЩИЕ ЗАДАЧИ
    if urgent_tasks:
        lines.append("")
        lines.append(f"<b>🔥 Горящие миссии ({len(urgent_tasks)}):</b>")
        lines.append("")

        for t in urgent_tasks:
            p_emoji = PRIORITY_EMOJI.get(t['priority'], '⚪️')
            name = t['name']

            tags_str = ""
            if t.get('tags'):
                tags_str = f" <b>[{', '.join(t['tags'])}]</b>"

            overdue = t.get('_urgency', 0) < 0
            if overdue:
                days = abs(t['_urgency'])
                marker = f"⚠️ просрочено {days} дн."
            else:
                marker = "🔥 сегодня"

            lines.append(f"{p_emoji}{tags_str} {name}")
            lines.append(f"     {marker}")
            lines.append("")

    # ВСЕ ЗАДАЧИ
    remaining = len(all_tasks) - len(urgent_tasks)
    if remaining > 0:
        lines.append(f"📋 И ещё <b>{remaining}</b> задач в работе")
        lines.append("")

    lines.append("–––––––")

    # NOTION КОНТЕКСТ
    if last_note:
        lines.append("")
        lines.append(f"<b>📓 Последняя заметка:</b>")
        lines.append(f"  {last_note}")
        lines.append("")
        lines.append("–––––––")

    # AI ИНСАЙТ (blockquote)
    insight = generate_personal_insight(urgent_tasks or all_tasks[:5], events)
    lines.append("")
    lines.append(f"<b>💡 Инсайт дня:</b>")
    lines.append(f"<blockquote>{insight}</blockquote>")
    lines.append("")
    lines.append("<b>🚀 Зажги сегодня!</b>")

    return "\n".join(lines)


def build_evening_briefing() -> str:
    """Собирает вечерний брифинг — итоги дня (HTML формат)."""
    import pytz
    tz = pytz.timezone(USER_TIMEZONE)
    now = datetime.now(tz)

    user_id = ALLOWED_TELEGRAM_ID or ""
    hidden_ids = get_hidden_tasks(user_id) if user_id else []
    all_tasks = get_my_tasks()
    if hidden_ids:
        all_tasks = [t for t in all_tasks if t.get('id', '') not in hidden_ids]
    urgent_tasks = get_urgent_tasks(hidden_ids)

    # XP
    xp_data = get_user_xp(user_id) if user_id else {'xp': 0, 'level': 1}
    current_xp = xp_data.get('xp', 0)
    rpg_title, _ = get_rpg_level(current_xp)

    weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    day_name = weekdays[now.weekday()]

    lines = []
    lines.append("<b>🌙 Итоги дня, Шеф</b>")
    lines.append(f"<i>{day_name}, {now.strftime('%d.%m.%Y')}</i>")
    lines.append(f"<i>{rpg_title}  •  {current_xp} XP</i>")
    lines.append("")

    lines.append("–––––––")
    lines.append("")

    # Что горело
    if urgent_tasks:
        overdue = [t for t in urgent_tasks if t.get('_urgency', 0) < 0]
        today = [t for t in urgent_tasks if t.get('_urgency', 0) == 0]

        if overdue:
            lines.append(f"<b>⚠️ Просрочено ({len(overdue)}):</b>")
            lines.append("")
            for t in overdue:
                tags_str = ""
                if t.get('tags'):
                    tags_str = f" <b>[{', '.join(t['tags'])}]</b>"
                days = abs(t.get('_urgency', 0))
                lines.append(f"  🔴{tags_str} {t['name']} ({days} дн.)")
                lines.append("")
            lines.append("–––––––")
            lines.append("")

        if today:
            lines.append(f"<b>📌 Было на сегодня ({len(today)}):</b>")
            lines.append("")
            for t in today:
                tags_str = ""
                if t.get('tags'):
                    tags_str = f" <b>[{', '.join(t['tags'])}]</b>"
                lines.append(f"  🟡{tags_str} {t['name']}")
                lines.append("")
            lines.append("–––––––")
            lines.append("")

    lines.append(f"📋 Всего активных задач: <b>{len(all_tasks)}</b>")
    lines.append("")
    lines.append("–––––––")
    lines.append("")
    lines.append("<b>🛌 Отдыхай, завтра новый день!</b>")

    return "\n".join(lines)
