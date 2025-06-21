# -*- coding: utf-8 -*-
import os
import json
import requests
import time # Импортируем для создания паузы
import io
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from google.oauth2 import service_account
from googleapiclient.discovery import build

CATEGORY_EMOJI_MAP = {
    "Задача": "✅",
    "Встреча": "🤝",
    "Идея": "💡",
    "Покупка": "🛒",
    "Мысль": "🤔",
    "Ссылка": "🔗",
    "Цитата": "💬",
    "Быстрая заметка": "📄" # На случай, если категория не определена
}

# --- Секретные ключи, ID и твой личный пропуск ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')
ALLOWED_TELEGRAM_ID = os.getenv('ALLOWED_TELEGRAM_ID') # Твой личный ID
ASSEMBLYAI_API_KEY = os.getenv('ASSEMBLYAI_API_KEY') # Новый ключ

# --- Функции для работы с API (без Whisper) ---
def download_telegram_file(file_id: str) -> io.BytesIO:
    """Загружает файл (голосовое сообщение) с серверов Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
    response = requests.get(url)
    file_path = response.json()['result']['file_path']
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    file_response = requests.get(file_url)
    return io.BytesIO(file_response.content)

def transcribe_with_assemblyai(audio_file_bytes) -> str:
    """Отправляет аудио в AssemblyAI и получает результат."""
    headers = {'authorization': ASSEMBLYAI_API_KEY}

    # 1. Отправляем файл на сервер AssemblyAI
    upload_response = requests.post(
        'https://api.assemblyai.com/v2/upload',
        headers=headers,
        data=audio_file_bytes
    )
    audio_url = upload_response.json()['upload_url']
    print("Аудиофайл успешно загружен в AssemblyAI.")

    # 2. Запускаем задачу транскрибации
    transcript_request = {'audio_url': audio_url, 'language_code': 'ru'}
    transcript_response = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        json=transcript_request,
        headers=headers
    )
    transcript_id = transcript_response.json()['id']
    print(f"Задача на транскрибацию создана с ID: {transcript_id}")

    # 3. Ждем результата (опрашиваем статус каждые пару секунд)
    while True:
        polling_response = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
            headers=headers
        )
        status = polling_response.json()['status']
        if status == 'completed':
            print("Транскрибация завершена.")
            return polling_response.json()['text']
        elif status == 'error':
            print("Ошибка транскрибации в AssemblyAI.")
            return None
        time.sleep(2) # Пауза перед следующей проверкой
        
def send_telegram_message(chat_id: str, text: str):
    """Отправляет текстовое сообщение пользователю в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'  # Включаем форматирование (жирный, курсив)
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Сообщение успешно отправлено пользователю {chat_id}")
    except Exception as e:
        print(f"Ошибка при отправке сообщения в Telegram: {e}")


def process_with_deepseek(text: str) -> dict:
    """Отправляет текст в DeepSeek и возвращает результат как СЛОВАРЬ."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    
    current_date_str = datetime.now().strftime('%Y-%m-%d')
    prompt = f"""
    Проанализируй следующую заметку пользователя, сделанную {current_date_str}. Твоя задача:
    1. Создать один общий заголовок для всей заметки.
    2. Определить одну общую категорию для заметки из списка: [Идея, Задача, Покупка, Встреча, Мысль, Ссылка, Цитата].
    3. Найти в тексте ВСЕ уникальные события, у которых есть дата и время.
    4. Вернуть результат строго в формате JSON. Поле "events" должно быть списком (массивом) объектов. ВАЖНО: Если в тексте нет ни одного события с датой и временем, поле "events" должно быть пустым массивом []. Не выдумывай события.

    Формат JSON:
    {{
      "main_title": "общий_заголовок_заметки",
      "category": "одна_общая_категория",
      "events": [
        {{
          "title": "название_первого_события",
          "datetime_iso": "YYYY-MM-DDTHH:MM:SS"
        }}
      ]
    }}

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
    
    json_string_from_ai = response.json()['choices'][0]['message']['content']
    return json.loads(json_string_from_ai)

def create_notion_page(title: str, content: str, category: str):
    """Создает новую страницу в базе данных Notion с иконкой."""
    url = 'https://api.notion.com/v1/pages'
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28'
    }
    
    # Выбираем эмодзи из нашей карты. Если категория новая, ставим эмодзи по умолчанию.
    page_icon = CATEGORY_EMOJI_MAP.get(category, "📄")

    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': title}}]},
        'Категория': {'select': {'name': category}}
    }
    
    children = []
    if content:
        children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}})
    
    payload = {
        'parent': {'database_id': NOTION_DATABASE_ID},
        'icon': {'type': 'emoji', 'emoji': page_icon}, # <--- ДОБАВИЛИ ИКОНКУ
        'properties': properties,
        'children': children
    }
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    print("Страница в Notion успешно создана с иконкой.")
    return response.json()['id'] # <--- ВОЗВРАЩАЕМ ID СТРАНИЦЫ

    
def create_google_calendar_event(title: str, description: str, start_time_iso: str):
    """Создает новое событие в Google Календаре с уведомлением."""
    try:
        # ... (код для creds и service не меняется)
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        service = build('calendar', 'v3', credentials=creds)
        
        calendar_id_to_use = os.getenv('GOOGLE_CALENDAR_ID')
        start_time = datetime.fromisoformat(start_time_iso)
        end_time = start_time + timedelta(hours=1)

        event = {
            'summary': title,
            'description': description,
            'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Europe/Kyiv'},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Europe/Kyiv'},
            # --- ДОБАВЛЯЕМ БЛОК С УВЕДОМЛЕНИЕМ ---
            'reminders': {
                'useDefault': False, # Не использовать стандартные настройки календаря
                'overrides': [
                    # Добавляем всплывающее уведомление за 15 минут
                    {'method': 'popup', 'minutes': 15},
                ],
            },
            # -----------------------------------------
        }

        created_event = service.events().insert(calendarId=calendar_id_to_use, body=event).execute()
        print("Событие в Google Calendar успешно создано с уведомлением.")
        return created_event.get('id') # <--- ВОЗВРАЩАЕМ ID СОБЫТИЯ
    except Exception as e:
        print(f"Ошибка при создании события в Google Calendar: {e}")
        return False

def delete_gcal_event(calendar_id: str, event_id: str):
    """Удаляет событие из Google Календаря."""
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        service = build('calendar', 'v3', credentials=creds)
        
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"Событие GCal {event_id} удалено.")
        return True
    except Exception as e:
        print(f"Ошибка при удалении события GCal: {e}")
        return False

def get_and_delete_last_log():
    """Получает последнюю запись из лога, извлекает данные и удаляет запись."""
    log_db_id = os.getenv('NOTION_LOG_DB_ID')
    if not log_db_id:
        return None

    # 1. Получаем последнюю запись из базы
    query_url = f"https://api.notion.com/v1/databases/{log_db_id}/query"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 1
    }
    response = requests.post(query_url, headers=headers, json=payload)
    results = response.json().get('results', [])

    if not results:
        print("Лог действий пуст.")
        return None

    # 2. Извлекаем данные из записи
    last_log_page = results[0]
    log_page_id = last_log_page['id']
    properties = last_log_page['properties']

    def get_text(prop):
        return prop['rich_text'][0]['text']['content'] if prop['rich_text'] else None

    action_details = {
        'notion_page_id': get_text(properties.get('NotionPageID')),
        'gcal_event_id': get_text(properties.get('GCalEventID')),
        'gcal_calendar_id': get_text(properties.get('GCalCalendarID'))
    }
    
    # 3. Удаляем саму запись из лога, чтобы не отменить ее еще раз
    delete_notion_page(log_page_id)
    
    print(f"Получены и удалены детали последнего действия: {action_details}")
    return action_details

def log_last_action(notion_page_id: str = None, gcal_event_id: str = None):
    """Записывает ID последних созданных объектов в лог-базу Notion."""
    log_db_id = os.getenv('NOTION_LOG_DB_ID')
    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}

    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': f"Action at {datetime.now()}"}}]}, # Главная колонка
        'NotionPageID': {'rich_text': [{'type': 'text', 'text': {'content': notion_page_id or ""}}]},
        'GCalEventID': {'rich_text': [{'type': 'text', 'text': {'content': gcal_event_id or ""}}]},
        'GCalCalendarID': {'rich_text': [{'type': 'text', 'text': {'content': os.getenv('GOOGLE_CALENDAR_ID') or ""}}]}
    }
    payload = {'parent': {'database_id': log_db_id}, 'properties': properties}
    requests.post(url, headers=headers, json=payload)
    print("Действие успешно залогировано.")

def delete_notion_page(page_id):
    """Архивирует (удаляет) страницу в Notion."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    payload = {'archived': True}
    requests.patch(url, headers=headers, json=payload)
    print(f"Страница Notion {page_id} удалена.")

        
# --- Основной обработчик с "Фейс-контролем" ---

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chat_id = None
        try:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            update = json.loads(body.decode('utf-8'))

            if 'message' not in update:
                self.send_response(200); self.end_headers(); return

            message = update['message']
            user_id = str(message['from']['id'])
            chat_id = message['chat']['id']

            if user_id != ALLOWED_TELEGRAM_ID:
                self.send_response(200); self.end_headers(); return
            
            # Логика команды /undo остается без изменений
            if message.get('text') == '/undo':
                # ... (здесь ваш рабочий код для /undo)
                self.send_response(200); self.end_headers(); return

            text_to_process = None

            if 'voice' in message:
                audio_bytes = download_telegram_file(message['voice']['file_id']).read()
                text_to_process = transcribe_with_assemblyai(audio_bytes)
                if not text_to_process:
                    send_telegram_message(chat_id, "❌ Не удалось распознать речь.")
            
            elif 'text' in message:
                text_to_process = message['text']

            if text_to_process:
                ai_data = process_with_deepseek(text_to_process)
                
                # Создание заметки в Notion (без изменений)
                notion_title = ai_data.get('main_title', 'Новая заметка')
                notion_category = ai_data.get('category', 'Мысль')
                try:
                    notion_page_id = create_notion_page(notion_title, text_to_process, notion_category)
                    if notion_page_id: log_last_action(notion_page_id=notion_page_id)
                    feedback_text = (f"✅ *Заметка в Notion создана!*\n\n*Название:* {notion_title}\n*Категория:* {notion_category}")
                    send_telegram_message(chat_id, feedback_text)
                except Exception as e:
                    send_telegram_message(chat_id, f"❌ *Ошибка при создании заметки в Notion:*\n`{e}`")

                # --- УМНАЯ ОБРАБОТКА СОБЫТИЙ ДЛЯ КАЛЕНДАРЯ ---
                calendar_events = ai_data.get('events', [])
                
                # 1. ФИЛЬТРУЕМ "ПУСТЫЕ" СОБЫТИЯ ОТ ИИ
                # Оставляем только те, у которых есть и название, и дата
                valid_events = [
                    event for event in calendar_events 
                    if event and event.get('title') and event.get('datetime_iso')
                ]

                # 2. Если после фильтрации остались реальные события, работаем с ними
                if valid_events:
                    created_events_titles = []
                    for event in valid_events:
                        try:
                            gcal_event_id = create_google_calendar_event(event['title'], "", event['datetime_iso'])
                            if gcal_event_id:
                                log_last_action(gcal_event_id=gcal_event_id)
                            created_events_titles.append(event['title'])
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ *Ошибка при создании события '{event['title']}':*\n`{e}`")
                    
                    # 3. Отправляем отчет только если что-то реально было создано
                    if created_events_titles:
                        feedback_text = (f"📅 *Добавлено {len(created_events_titles)} события в Календарь:*\n- " + "\n- ".join(created_events_titles))
                        send_telegram_message(chat_id, feedback_text)

        except Exception as e:
            if chat_id:
                send_telegram_message(chat_id, f"🤯 *Произошла глобальная ошибка!*\nПожалуйста, проверьте логи Vercel.\n`{e}`")
            print(f"Произошла глобальная ошибка: {e}")
        
        self.send_response(200)
        self.end_headers()
        return
