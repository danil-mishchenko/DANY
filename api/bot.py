# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Секретные ключи, ID и твой личный пропуск ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')
ALLOWED_TELEGRAM_ID = os.getenv('ALLOWED_TELEGRAM_ID') # Твой личный ID

# --- Функции для работы с API (без Whisper) ---

def process_with_deepseek(text: str) -> dict:
    """Отправляет текст в DeepSeek для анализа, улучшения и извлечения данных."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    current_date_str = datetime.now().strftime('%Y-%m-%d')
    prompt = f"""
    Проанализируй следующую заметку пользователя, сделанную {current_date_str}. Твоя задача:
    1. Определить наиболее подходящую категорию для этой заметки из списка: [Идея, Задача, Покупка, Встреча, Мысль, Ссылка, Цитата].
    2. Слегка переписать и улучшить текст заметки: исправь опечатки, улучши стиль, сделай заголовок и основной текст более четкими.
    3. Проверить, содержит ли заметка конкретную дату и время. Если да, верни дату и время в формате ISO 8601 для часового пояса Europe/Kyiv. Если время не указано, используй 12:00. Если дата не указана, верни null. Учитывай относительные даты, как "завтра", "в среду".
    4. Верни результат строго в формате JSON, без каких-либо других слов и пояснений.

    Формат JSON: {{ "category": "...", "beautified_title": "...", "beautified_content": "...", "event_datetime_iso": "..." }}

    Заметка:
    ---
    {text}
    ---
    """
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']

def create_notion_page(title: str, content: str, category: str):
    """Создает новую страницу в базе данных Notion."""
    # ... (код этой функции не меняется, можно скопировать из предыдущего ответа)
    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    properties = {'Name': {'title': [{'type': 'text', 'text': {'content': title}}]}, 'Категория': {'select': {'name': category}}}
    children = []
    if content:
        children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}})
    payload = {'parent': {'database_id': NOTION_DATABASE_ID}, 'properties': properties, 'children': children}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    print("Страница в Notion успешно создана.")

def create_google_calendar_event(title: str, description: str, start_time_iso: str):
    """Создает новое событие в Google Календаре, указанном в переменных окружения."""
    try:
        # 1. Получаем креды для доступа
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        service = build('calendar', 'v3', credentials=creds)
        
        # 2. Получаем ID нужного календаря из переменных окружения
        calendar_id_to_use = os.getenv('GOOGLE_CALENDAR_ID')

        # 3. Подготавливаем данные о времени события
        start_time = datetime.fromisoformat(start_time_iso)
        end_time = start_time + timedelta(hours=1)

        # 4. Собираем тело запроса для API
        event = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Europe/Kyiv',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Europe/Kyiv',
            },
        }

        # 5. Отправляем запрос в Google API с УКАЗАНИЕМ КОНКРЕТНОГО КАЛЕНДАРЯ
        service.events().insert(calendarId=calendar_id_to_use, body=event).execute()
        
        print("Событие в Google Calendar успешно создано.")
        return True
        
    except Exception as e:
        print(f"Ошибка при создании события в Google Calendar: {e}")
        return False

# --- Основной обработчик с "Фейс-контролем" ---

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            update = json.loads(body.decode('utf-8'))

            if 'message' not in update:
                self.send_response(200); self.end_headers(); return

            message = update['message']
            user_id = str(message['from']['id'])

            # =======================================================
            #           ⚡️ ГЛАВНАЯ ПРОВЕРКА БЕЗОПАСНОСТИ ⚡️
            # =======================================================
            if user_id != ALLOWED_TELEGRAM_ID:
                print(f"ОТКАЗ В ДОСТУПЕ: Попытка использования от юзера {user_id}")
                self.send_response(200) # Тихо игнорируем, отвечая Telegram "OK"
                self.end_headers()
                return # Прекращаем выполнение
            # =======================================================

            if 'text' in message:
                text_to_process = message['text']

                ai_result_str = process_with_deepseek(text_to_process)
                ai_data = json.loads(ai_result_str)
                
                title = ai_data.get('beautified_title', 'Новая заметка')
                content = ai_data.get('beautified_content', '')
                category = ai_data.get('category', 'Мысль')
                event_time_iso = ai_data.get('event_datetime_iso')

                try:
                    create_notion_page(title, content, category)
                except Exception as e:
                    print(f"Ошибка при создании страницы в Notion: {e}")

                if event_time_iso:
                    try:
                        create_google_calendar_event(title, content, event_time_iso)
                    except Exception as e:
                        print(f"Ошибка при создании события в Google Calendar: {e}")

        except Exception as e:
            print(f"Произошла глобальная ошибка: {e}")
        
        self.send_response(200)
        self.end_headers()
        return
