# -*- coding: utf-8 -*-
import os
import json
import requests
import time # Импортируем для создания паузы
import io
from datetime import datetime, timedelta, timezone
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

def send_telegram_message(chat_id: str, text: str, use_html: bool = False, add_undo_button: bool = False):
    """Отправляет текстовое сообщение пользователю, опционально с кнопкой "Отменить"."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML' if use_html else 'Markdown'
    }

    # Если нужно, добавляем кнопку "Отменить"
    if add_undo_button:
        keyboard = {
            "inline_keyboard": [[
                {
                    "text": "↩️ Отменить",
                    "callback_data": "undo_last_action" # Метка, которую мы будем ловить
                }
            ]]
        }
        payload['reply_markup'] = json.dumps(keyboard)

    try:
        requests.post(url, json=payload).raise_for_status()
    except Exception as e:
        print(f"Ошибка при отправке сообщения в Telegram: {e}")

def send_initial_status_message(chat_id: str, text: str):
    """Отправляет начальное сообщение и возвращает его ID для последующего редактирования."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        # Возвращаем ID отправленного сообщения
        return response.json()['result']['message_id']
    except Exception as e:
        print(f"Ошибка при отправке начального сообщения: {e}")
        return None

def edit_telegram_message(chat_id: str, message_id: int, new_text: str, use_html: bool = False, add_undo_button: bool = False):
    """Редактирует существующее сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': new_text,
        'parse_mode': 'HTML' if use_html else 'Markdown'
    }
    if add_undo_button:
        keyboard = {"inline_keyboard": [[{"text": "↩️ Отменить", "callback_data": "undo_last_action"}]]}
        payload['reply_markup'] = json.dumps(keyboard)
    
    try:
        requests.post(url, json=payload).raise_for_status()
    except Exception as e:
        print(f"Ошибка при редактировании сообщения: {e}")

def get_latest_notes(limit: int = 5):
    """Запрашивает у Notion последние N страниц из основной базы данных."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": limit
    }
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json().get('results', [])

# --- НОВЫЕ ФУНКЦИИ ДЛЯ ПОИСКА ---

def search_notion_pages(query: str):
    """Ищет страницы по содержимому в нашей базе данных с помощью фильтра."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    
    # Создаем фильтр, который ищет текст в свойстве "Содержание"
    payload = {
        "filter": {
            "property": "Содержание",
            "rich_text": {
                "contains": query
            }
        },
        "page_size": 5 # Возвращаем до 5 самых релевантных страниц
    }
    
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    
    return response.json().get('results', [])
    
def get_notion_page_content(page_id: str) -> str:
    """Получает все текстовое содержимое со страницы Notion."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    blocks = response.json().get('results', [])
    
    content = []
    for block in blocks:
        block_type = block['type']
        if block_type in ['paragraph', 'bulleted_list_item', 'heading_1', 'heading_2', 'heading_3']:
            rich_text_array = block.get(block_type, {}).get('rich_text', [])
            for rich_text in rich_text_array:
                content.append(rich_text.get('plain_text', ''))
        # Добавим обработку блока кода, который мы использовали ранее
        elif block_type == 'code':
            rich_text_array = block.get('code', {}).get('rich_text', [])
            for rich_text in rich_text_array:
                content.append(rich_text.get('plain_text', ''))

    return "\n".join(content)

def summarize_for_search(context: str, question: str) -> str:
    """Отправляет контекст и вопрос в DeepSeek для генерации ответа."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    prompt = f"""
    Основываясь СТРОГО на предоставленном ниже тексте из заметки, дай краткий и четкий ответ на вопрос пользователя. Не выдумывай ничего. Если в тексте нет ответа, сообщи об этом.
    
    Текст заметки:
    ---
    {context}
    ---
    Вопрос пользователя: "{question}"
    """
    data = {"model": "deepseek-chat", "messages": [{"role": "system", "content": "Ты — полезный ассистент, отвечающий на вопросы по тексту."}, {"role": "user", "content": prompt}]}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def parse_to_notion_blocks(formatted_text: str) -> list:
    """
    Превращает текст в нативные блоки Notion, корректно находя URL в любой части строки
    и используя остальной текст как подпись к закладке.
    """
    blocks = []
    # Паттерн для поиска URL в любом месте строки
    url_pattern = re.compile(r'https?://\S+')

    for line in formatted_text.split('\n'):
        stripped_line = line.strip()
        if not stripped_line:
            continue

        # 1. Ищем URL в строке
        match = url_pattern.search(stripped_line)
        
        if match:
            # URL найден
            url = match.group(0)
            
            # 2. Весь остальной текст на строке делаем подписью
            # Удаляем URL и лишние символы-разделители
            caption_text = url_pattern.sub('', stripped_line).strip(' -').strip()
            
            # 3. Создаем блок закладки с подписью
            bookmark_block = {
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": url}
            }
            # Добавляем подпись, только если она не пустая
            if caption_text:
                bookmark_block["bookmark"]["caption"] = [{"type": "text", "text": {"content": caption_text}}]

            blocks.append(bookmark_block)
            continue

        # 4. Если URL в строке не найден, обрабатываем как обычный текст (список или параграф)
        is_bullet_item = stripped_line.startswith('- ')
        block_type = "bulleted_list_item" if is_bullet_item else "paragraph"
        clean_line = stripped_line.lstrip('- ') if is_bullet_item else stripped_line
        
        # Парсим inline-форматирование (жирный/курсив)
        rich_text_objects = []
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*)', clean_line)
        for part in filter(None, parts):
            is_bold = part.startswith('**') and part.endswith('**')
            is_italic = part.startswith('*') and part.endswith('*')
            content = part.strip('**').strip('*')
            annotations = {"bold": is_bold, "italic": is_italic}
            rich_text_objects.append({"type": "text", "text": {"content": content}, "annotations": annotations})

        if rich_text_objects:
            if block_type == "bulleted_list_item":
                blocks.append({"object": "block", "type": block_type, "bulleted_list_item": {"rich_text": rich_text_objects}})
            else:
                blocks.append({"object": "block", "type": block_type, "paragraph": {"rich_text": rich_text_objects}})
            
    return blocks

    
def process_with_deepseek(text: str) -> dict:
    """Отправляет текст в DeepSeek для умного форматирования и извлечения данных."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    
    current_datetime_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    prompt = f"""
    Твоя роль: умный редактор заметок. Проанализируй заметку пользователя. Текущее время для расчетов: {current_datetime_str}.
    Задачи:
    1. Язык: Сохраняй язык оригинала. Не переводи.
    2. Заголовок и Категория: Создай емкий заголовок и определи категорию из списка: [Идея, Задача, Покупка, Встреча, Мысль, Ссылка, Цитата].
    3. Форматирование: Очень Красиво отформатируй текст, можешь оптимизировать если где-то явное пустословие. Заметки должны быть прекрасными и эстетичными.
        - Заголовки - жирным, можно с 1 эмодзи. 
        - Списки - через дефис с эмодзи. 
        - Комментарии - курсивом.
        - ВАЖНО: Каждую ссылку (URL) всегда размещай на отдельной строке.
    4. Если есть обращение к Deepseek (также дипсик, дип сик и тд.) то воспринимай тот отрезок текста как обращение к тебе, как поправка к промпту.
    5. События: Найди ВСЕ события с датой/временем. Учитывай относительные даты ("завтра", "через 30 минут"). Если их нет - верни пустой список "events": [].
    6. Результат: Верни строго JSON.
    Формат JSON: {{"main_title": "...", "category": "...", "formatted_body": "...", "events": [{{"title": "...", "datetime_iso": "..."}}]}}
    Заметка: --- {text} ---
    """
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return json.loads(response.json()['choices'][0]['message']['content'])

# ИСПРАВЛЕННАЯ ФУНКЦИЯ для создания настоящих rich-text страниц
def create_notion_page(title: str, formatted_content: str, category: str):
    """Создает новую страницу в Notion, дублируя контент в свойство 'Содержание' для поиска."""
    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    page_icon = CATEGORY_EMOJI_MAP.get(category, "📄")
    
    # Обрезаем контент до 2000 символов, т.к. это лимит для одного rich_text поля в Notion
    searchable_content = formatted_content[:2000]

    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': title}}]},
        'Категория': {'select': {'name': category}},
        # ДОБАВЛЯЕМ НОВОЕ ПОЛЕ: копируем сюда текст заметки для поиска
        'Содержание': {'rich_text': [{'type': 'text', 'text': {'content': searchable_content}}]}
    }
    
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

def log_last_action(properties: dict = None, notion_page_id: str = None, gcal_event_id: str = None):
    """Записывает действие или состояние в лог-базу Notion.
    Может принимать либо готовый словарь properties, либо ID для его создания.
    """
    log_db_id = os.getenv('NOTION_LOG_DB_ID')
    if not log_db_id:
        print("ОШИБКА ЛОГИРОВАНИЯ: Переменная NOTION_LOG_DB_ID не найдена.")
        return

    # Если готовые properties не переданы, создаем их по старой схеме
    if properties is None:
        properties = {
            'Name': {'title': [{'type': 'text', 'text': {'content': f"Action at {datetime.now()}"}}]},
            'NotionPageID': {'rich_text': [{'type': 'text', 'text': {'content': notion_page_id or ""}}]},
            'GCalEventID': {'rich_text': [{'type': 'text', 'text': {'content': gcal_event_id or ""}}]},
            'GCalCalendarID': {'rich_text': [{'type': 'text', 'text': {'content': os.getenv('GOOGLE_CALENDAR_ID') or ""}}]}
        }

    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {'parent': {'database_id': log_db_id}, 'properties': properties}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Действие успешно залогировано: {properties.get('Name', {}).get('title', [{}])[0].get('text', {}).get('content')}")
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА ЛОГИРОВАНИЯ: {e}")

def delete_notion_page(page_id):
    """Архивирует (удаляет) страницу в Notion."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    payload = {'archived': True}
    requests.patch(url, headers=headers, json=payload)
    print(f"Страница Notion {page_id} удалена.")

        
# --- ФИНАЛЬНЫЙ ОБРАБОТЧИК И ВСЕ ЕГО ПОМОЩНИКИ ---

def set_user_state(user_id: str, state: str, page_id: str):
    """Создает запись о намерении пользователя в лог-базе."""
    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': f"State for {user_id}: {state}"}}]},
        'UserID': {'rich_text': [{'type': 'text', 'text': {'content': user_id}}]},
        'NotionPageID': {'rich_text': [{'type': 'text', 'text': {'content': page_id}}]},
        'State': {'select': {'name': state}}
    }
    log_last_action(properties=properties)

def get_user_state(user_id: str):
    """Проверяет, есть ли для пользователя активное состояние, и удаляет его."""
    log_db_id = os.getenv('NOTION_LOG_DB_ID')
    if not log_db_id: return None
    
    payload = {
        "filter": {"and": [ {"property": "UserID", "rich_text": {"equals": user_id}}, {"property": "State", "select": {"is_not_empty": True}} ]},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}], "page_size": 1
    }
    query_url = f"https://api.notion.com/v1/databases/{log_db_id}/query"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    response = requests.post(query_url, headers=headers, json=payload)
    results = response.json().get('results', [])

    if not results: return None
    
    state_page = results[0]
    state_page_id = state_page['id']
    properties = state_page['properties']
    
    def get_text(prop): return prop['rich_text'][0]['text']['content'] if prop.get('rich_text') else None
    
    state_details = {
        'state': properties.get('State', {}).get('select', {}).get('name'),
        'page_id': get_text(properties.get('NotionPageID'))
    }
    
    delete_notion_page(state_page_id) # Удаляем запись о состоянии, т.к. мы ее обработаем
    return state_details

def add_to_notion_page(page_id: str, text_to_add: str):
    """Добавляет новые блоки текста в конец страницы Notion."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    new_blocks = parse_to_notion_blocks(text_to_add)
    payload = {'children': new_blocks}
    requests.patch(url, headers=headers, json=payload).raise_for_status()


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chat_id = None
        try:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            update = json.loads(body.decode('utf-8'))

            message = update.get('message')
            callback_query = update.get('callback_query')

            # --- ОБРАБОТКА НАЖАТИЯ КНОПОК ---
            if callback_query:
                callback_data = callback_query['data']
                chat_id = callback_query['message']['chat']['id']
                callback_query_id = callback_query['id']
                requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery?callback_query_id={callback_query_id}")

                if callback_data == 'undo_last_action':
                    last_action = get_and_delete_last_log()
                    if last_action:
                        if last_action.get('notion_page_id'): delete_notion_page(last_action['notion_page_id'])
                        if last_action.get('gcal_event_id') and last_action.get('gcal_calendar_id'): delete_gcal_event(last_action['gcal_calendar_id'], last_action['gcal_event_id'])
                        send_telegram_message(chat_id, "✅ Последнее действие отменено.")
                    else:
                        send_telegram_message(chat_id, "🤔 Не найдено действий для отмены.")
                
                elif callback_data.startswith('delete_notion_'):
                    page_id_to_delete = callback_data.split('_', 2)[2]
                    try:
                        delete_notion_page(page_id_to_delete)
                        send_telegram_message(chat_id, f"🗑️ Заметка удалена.")
                    except Exception as e:
                        send_telegram_message(chat_id, f"❌ Не удалось удалить заметку. Ошибка: {e}")

                elif callback_data.startswith('add_to_notion_'):
                    page_id = callback_data.split('_', 3)[3]
                    set_user_state(str(chat_id), 'awaiting_add_text', page_id)
                    send_telegram_message(chat_id, "▶️ Введите текст, который нужно *добавить* в конец заметки:")
                
                self.send_response(200); self.end_headers(); return

            # --- ОБРАБОТКА СООБЩЕНИЙ ---
            if not message:
                self.send_response(200); self.end_headers(); return

            user_id = str(message['from']['id'])
            chat_id = message['chat']['id']

            if user_id != ALLOWED_TELEGRAM_ID:
                self.send_response(200); self.end_headers(); return
            
            # ПРОВЕРКА СОСТОЯНИЯ: не ждем ли мы текст для добавления?
            user_state = get_user_state(user_id)
            if user_state:
                if user_state.get('state') == 'awaiting_add_text':
                    page_id_to_edit = user_state['page_id']
                    text_to_add = message.get('text', '')
                    if text_to_add:
                        add_to_notion_page(page_id_to_edit, text_to_add)
                        send_telegram_message(chat_id, "✅ Текст успешно добавлен в заметку!")
                    else:
                        send_telegram_message(chat_id, "Отмена. Получено пустое сообщение.")
                    self.send_response(200); self.end_headers(); return
            
            text = message.get('text', '')
            
            # ПРОВЕРКА КОМАНД
            if text == '/notes':
                send_telegram_message(chat_id, "🔎 Ищу 3 последние заметки...")
                latest_notes = get_latest_notes(3)
                if not latest_notes:
                    send_telegram_message(chat_id, "😔 Заметок пока нет.")
                else:
                    send_telegram_message(chat_id, f"👇 Вот что я нашел:")
                    for note in latest_notes:
                        page_id = note['id']
                        title_parts = note.get('properties', {}).get('Name', {}).get('title', [])
                        page_title = title_parts[0]['plain_text'] if title_parts else "Без названия"
                        keyboard = {"inline_keyboard": [[ {"text": "➕ Добавить", "callback_data": f"add_to_notion_{page_id}"}, {"text": "🗑️ Удалить", "callback_data": f"delete_notion_{page_id}"} ]]}
                        message_text = f"*{page_title}*"
                        payload = {'chat_id': chat_id, 'text': message_text, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(keyboard)}
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload)
                self.send_response(200); self.end_headers(); return

            elif text.startswith('/search '):
                query = text.split(' ', 1)[1]
                if not query:
                    send_telegram_message(chat_id, "Пожалуйста, укажите, что нужно найти после команды /search.")
                    self.send_response(200); self.end_headers(); return
                
                send_telegram_message(chat_id, f"🔎 Ищу заметки по запросу: *{query}*...")
                search_results = search_notion_pages(query)
                if not search_results:
                    send_telegram_message(chat_id, "😔 Ничего не найдено по вашему запросу.")
                    self.send_response(200); self.end_headers(); return

                top_result_id = search_results[0]['id']
                page_content = get_notion_page_content(top_result_id)
                if not page_content:
                    send_telegram_message(chat_id, "🤔 Нашел подходящую заметку, но она пуста.")
                    self.send_response(200); self.end_headers(); return

                answer = summarize_for_search(page_content, query)
                page_title = search_results[0].get('properties', {}).get('Name', {}).get('title', [{}])[0].get('plain_text', 'Без названия')
                final_response = f"💡 *Результат поиска по заметке «{page_title}»*:\n\n{answer}"
                send_telegram_message(chat_id, final_response)
                self.send_response(200); self.end_headers(); return
                
            elif text == '/undo':
                send_telegram_message(chat_id, "Пожалуйста, используйте кнопку '↩️ Отменить' под сообщением.")
                self.send_response(200); self.end_headers(); return
                
            # --- ЛОГИКА СОЗДАНИЯ НОВОЙ ЗАМЕТКИ (если это не команда) ---
            # 1. СНАЧАЛА ОПРЕДЕЛЯЕМ, КАКОЙ ТЕКСТ ОБРАБАТЫВАТЬ
            text_to_process = None
            is_text_message = False
            if 'voice' in message:
                send_telegram_message(chat_id, "⏳ Распознаю речь...")
                audio_bytes = download_telegram_file(message['voice']['file_id']).read()
                text_to_process = transcribe_with_assemblyai(audio_bytes)
                if not text_to_process: send_telegram_message(chat_id, "❌ Не удалось распознать речь.")
            elif 'text' in message:
                is_text_message = True
                text_to_process = message['text']

            # 2. И ТОЛЬКО ПОТОМ, ЕСЛИ ТЕКСТ ЕСТЬ, ЗАПУСКАЕМ ОБРАБОТКУ
            if text_to_process:
                status_message_id = None
                if is_text_message:
                    progress_bar = "⬜️⬜️⬜️⬜️⬜️⬜️ 0%"
                    status_message_id = send_initial_status_message(chat_id, f"⏳ Анализирую...\n`{progress_bar}`")

                if status_message_id:
                    progress_bar = "🟩🟩⬜️⬜️⬜️⬜️ 33%"
                    edit_telegram_message(chat_id, status_message_id, f"⏳ Анализирую...\n`{progress_bar}`")
                
                ai_data = process_with_deepseek(text_to_process)
                notion_title = ai_data.get('main_title', 'Новая заметка')
                notion_category = ai_data.get('category', 'Мысль')
                formatted_body = ai_data.get('formatted_body', text_to_process)
                
                if status_message_id:
                    progress_bar = "🟩🟩🟩🟩⬜️⬜️ 66%"
                    edit_telegram_message(chat_id, status_message_id, f"⏳ Сохраняю в Notion...\n`{progress_bar}`")

                try:
                    notion_page_id = create_notion_page(notion_title, formatted_body, notion_category)
                    if notion_page_id: log_last_action(notion_page_id=notion_page_id)
                    if not is_text_message:
                        send_telegram_message(chat_id, f"✅ *Заметка в Notion создана!*\n\n*Название:* {notion_title}\n*Категория:* {notion_category}", add_undo_button=True)
                except Exception as e:
                    detailed_error = e.response.text if hasattr(e, 'response') else str(e)
                    final_text = f"❌ *Ошибка при создании заметки в Notion:*\n<pre>{detailed_error}</pre>"
                    if status_message_id: edit_telegram_message(chat_id, status_message_id, final_text, use_html=True)
                    else: send_telegram_message(chat_id, final_text, use_html=True)
                    self.send_response(200); self.end_headers(); return

                valid_events = [event for event in ai_data.get('events', []) if event and event.get('title') and event.get('datetime_iso')]
                created_events_titles = []
                if valid_events:
                    if status_message_id:
                        progress_bar = "🟩🟩🟩🟩🟩🟩 99%"
                        edit_telegram_message(chat_id, status_message_id, f"⏳ Добавляю в календарь...\n`{progress_bar}`")
                    for event in valid_events:
                        try:
                            gcal_event_id = create_google_calendar_event(event['title'], formatted_body, event['datetime_iso'])
                            if gcal_event_id: log_last_action(gcal_event_id=gcal_event_id)
                            created_events_titles.append(event['title'])
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ *Ошибка при создании события '{event['title']}':*\n`{e}`")
                
                final_report_text = f"✅ *Заметка «{notion_title}» создана!*\n_Категория: {notion_category}_"
                if created_events_titles:
                    final_report_text += "\n\n📅 *Добавлено в календарь:*\n- " + "\n- ".join(created_events_titles)
                if status_message_id:
                    edit_telegram_message(chat_id, status_message_id, final_report_text, add_undo_button=True)
                elif created_events_titles:
                    send_telegram_message(chat_id, f"📅 *Добавлено {len(created_events_titles)} события в Календарь:*\n- " + "\n- ".join(created_events_titles), add_undo_button=True)
        except Exception as e:
            if chat_id:
                send_telegram_message(chat_id, f"🤯 *Произошла глобальная ошибка!*\nПожалуйста, проверьте логи Vercel.\n`{e}`")
            print(f"Произошла глобальная ошибка: {e}")
        
        self.send_response(200)
        self.end_headers()
        return
