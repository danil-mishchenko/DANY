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
import re

def markdown_to_gcal_html(md_text: str) -> str:
    """Конвертирует простой Markdown в HTML для Google Календаря."""
    # Заменяем **жирный** на <b>жирный</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', md_text)
    # Заменяем *курсив* на <i>курсив</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    return text
    
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
NOTION_LOG_DB_ID = os.getenv('NOTION_LOG_DB_ID')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')
GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID') # <--- ВОТ ЭТА СТРОКА ПРОПАЛА
ALLOWED_TELEGRAM_ID = os.getenv('ALLOWED_TELEGRAM_ID')
ASSEMBLYAI_API_KEY = os.getenv('ASSEMBLYAI_API_KEY')

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

def send_telegram_message(chat_id: str, text: str, use_html: bool = False):
    """Отправляет текстовое сообщение пользователю в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Определяем режим форматирования на основе нового параметра
    parse_mode = 'HTML' if use_html else 'Markdown'
    
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Сообщение успешно отправлено пользователю {chat_id}")
    except Exception as e:
        print(f"Ошибка при отправке сообщения в Telegram: {e}")

def parse_to_notion_blocks(formatted_text: str) -> list:
    """Превращает текст с Markdown-разметкой в нативные блоки Notion (параграфы, списки, жирный/курсив)."""
    blocks = []
    for line in formatted_text.split('\n'):
        if not line.strip(): continue # Пропускаем пустые строки

        # Определяем тип блока (список или параграф)
        block_type = "bulleted_list_item" if line.strip().startswith('- ') else "paragraph"
        # Убираем маркер списка для дальнейшей обработки
        clean_line = line.strip().lstrip('- ')
        
        # Создаем rich_text объекты с аннотациями для жирного и курсива
        rich_text_objects = []
        # Используем re.split, чтобы разбить строку по ** или *
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*)', clean_line)
        
        for part in parts:
            if not part: continue
            
            is_bold = part.startswith('**') and part.endswith('**')
            is_italic = part.startswith('*') and part.endswith('*')
            
            content = part
            annotations = {"bold": False, "italic": False}

            if is_bold:
                content = part.strip('**')
                annotations["bold"] = True
            elif is_italic:
                content = part.strip('*')
                annotations["italic"] = True

            rich_text_objects.append({
                "type": "text",
                "text": {"content": content},
                "annotations": annotations
            })

        # Собираем финальный блок
        if block_type == "bulleted_list_item":
            blocks.append({"object": "block", "type": block_type, "bulleted_list_item": {"rich_text": rich_text_objects}})
        else:
            blocks.append({"object": "block", "type": block_type, "paragraph": {"rich_text": rich_text_objects}})
            
    return blocks
    
def process_with_deepseek(text: str) -> dict:
    """Отправляет текст в DeepSeek для умного форматирования и извлечения данных."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    
    # ИСПРАВЛЕНИЕ: Даем ИИ точное текущее время для расчета относительных дат
    current_datetime_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    prompt = f"""
    Твоя роль: умный редактор заметок. Проанализируй заметку пользователя. Текущее время: {current_datetime_str}.
    Задачи:
    1. Язык: Сохраняй язык оригинала. Не переводи.
    2. Заголовок и Категория: Создай емкий заголовок и определи категорию из списка: [Идея, Задача, Покупка, Встреча, Мысль, Ссылка, Цитата].
    3. Форматирование: Красиво отформатируй текст. Заголовки - жирным. Списки - через дефис с эмодзи. Комментарии - курсивом.
    4. События: Найди ВСЕ события с датой/временем. Учитывай относительные даты ("завтра", "через 30 минут"). Конвертируй их в абсолютный формат YYYY-MM-DDTHH:MM:SS. Если событий нет - верни пустой список "events": [].
    5. Результат: Верни строго JSON.
    Формат JSON: {{"main_title": "...", "category": "...", "formatted_body": "...", "events": [{{"title": "...", "datetime_iso": "..."}}]}}
    Заметка: --- {text} ---
    """
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return json.loads(response.json()['choices'][0]['message']['content'])

# ИСПРАВЛЕННАЯ ФУНКЦИЯ для создания настоящих rich-text страниц
def create_notion_page(title: str, formatted_content: str, category: str):
    """Создает новую страницу в Notion с нативными блоками (списки, параграфы)."""
    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    page_icon = CATEGORY_EMOJI_MAP.get(category, "📄")
    properties = {'Name': {'title': [{'type': 'text', 'text': {'content': title}}]}, 'Категория': {'select': {'name': category}}}
    
    # Вызываем нашу новую функцию-парсер
    children = parse_to_notion_blocks(formatted_content)
    
    payload = {'parent': {'database_id': NOTION_DATABASE_ID}, 'icon': {'type': 'emoji', 'emoji': page_icon}, 'properties': properties, 'children': children}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()['id']

def create_google_calendar_event(title: str, description: str, start_time_iso: str):
    """Создает событие в Google Календаре, конвертируя описание в HTML."""
    creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(creds_info)
    service = build('calendar', 'v3', credentials=creds)
    start_time = datetime.fromisoformat(start_time_iso)
    end_time = start_time + timedelta(hours=1)
    
    # Конвертируем описание в HTML перед отправкой
    html_description = markdown_to_gcal_html(description)

    event = {
        'summary': title,
        'description': html_description, # <--- ИСПОЛЬЗУЕМ HTML
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Europe/Kyiv'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Europe/Kyiv'},
        'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 15}]}
    }
    created_event = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
    return created_event.get('id')

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

            if 'message' not in update: self.send_response(200); self.end_headers(); return
            message = update['message']
            user_id = str(message['from']['id'])
            chat_id = message['chat']['id']

            if user_id != ALLOWED_TELEGRAM_ID: self.send_response(200); self.end_headers(); return
            
            if message.get('text') == '/undo':
                last_action = get_and_delete_last_log()
                if last_action:
                    if last_action.get('notion_page_id'): delete_notion_page(last_action['notion_page_id'])
                    if last_action.get('gcal_event_id') and last_action.get('gcal_calendar_id'): delete_gcal_event(last_action['gcal_calendar_id'], last_action['gcal_event_id'])
                    send_telegram_message(chat_id, "✅ Последнее действие отменено.")
                else:
                    send_telegram_message(chat_id, "🤔 Не найдено действий для отмены.")
                self.send_response(200); self.end_headers(); return

            text_to_process = None
            if 'voice' in message:
                audio_bytes = download_telegram_file(message['voice']['file_id']).read()
                text_to_process = transcribe_with_assemblyai(audio_bytes)
                if not text_to_process: send_telegram_message(chat_id, "❌ Не удалось распознать речь.")
            elif 'text' in message:
                text_to_process = message['text']

            if text_to_process:
                ai_data = process_with_deepseek(text_to_process)
                
                notion_title = ai_data.get('main_title', 'Новая заметка')
                notion_category = ai_data.get('category', 'Мысль')
                formatted_body = ai_data.get('formatted_body', text_to_process)
                
                # Создание заметки в Notion
                try:
                    notion_page_id = create_notion_page(notion_title, formatted_body, notion_category)
                    if notion_page_id:
                        log_last_action(notion_page_id=notion_page_id)
                    send_telegram_message(chat_id, f"✅ *Заметка в Notion создана!*\n\n*Название:* {notion_title}\n*Категория:* {notion_category}")
                except Exception as e:
                    detailed_error = e.response.text if hasattr(e, 'response') else str(e)
                    send_telegram_message(chat_id, f"❌ *Ошибка при создании заметки в Notion:*\n<pre>{detailed_error}</pre>", use_html=True)

                # Обработка событий для Календаря
                calendar_events = ai_data.get('events', [])
                valid_events = [
                    event for event in calendar_events 
                    if event and event.get('title') and event.get('datetime_iso')
                ]

                if valid_events:
                    created_events_titles = []
                    for event in valid_events:
                        try:
                            # Передаем отформатированное тело как описание
                            gcal_event_id = create_google_calendar_event(event['title'], formatted_body, event['datetime_iso'])
                            if gcal_event_id:
                                log_last_action(gcal_event_id=gcal_event_id)
                            created_events_titles.append(event['title'])
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ *Ошибка при создании события '{event['title']}':*\n`{e}`")
                    
                    if created_events_titles:
                        send_telegram_message(chat_id, f"📅 *Добавлено {len(created_events_titles)} события в Календарь:*\n- " + "\n- ".join(created_events_titles))

        except Exception as e:
            if chat_id:
                send_telegram_message(chat_id, f"🤯 *Произошла глобальная ошибка!*\nПожалуйста, проверьте логи Vercel.\n`{e}`")
            print(f"Произошла глобальная ошибка: {e}")
        
        self.send_response(200)
        self.end_headers()
        return
