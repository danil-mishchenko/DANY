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

        service.events().insert(calendarId=calendar_id_to_use, body=event).execute()
        
        print("Событие в Google Calendar успешно создано с уведомлением.")
        return True
    except Exception as e:
        print(f"Ошибка при создании события в Google Calendar: {e}")
        return False
        
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

            text_to_process = None

            # Шаг 1: Проверяем, есть ли голосовое сообщение
            if 'voice' in message:
                print("Получено голосовое сообщение. Начинаю транскрибацию...")
                audio_bytes = download_telegram_file(message['voice']['file_id']).read()
                text_to_process = transcribe_with_assemblyai(audio_bytes)
                if not text_to_process:
                    send_telegram_message(chat_id, "❌ Не удалось распознать речь в голосовом сообщении.")
            
            # Шаг 2: Если голосового нет, проверяем, есть ли текст
            elif 'text' in message:
                print("Получено текстовое сообщение.")
                text_to_process = message['text']

            # Если после всех проверок у нас есть текст для обработки, запускаем магию
            if text_to_process:
                ai_result_str = process_with_deepseek(text_to_process)
                ai_data = json.loads(ai_result_str)
                
                title = ai_data.get('beautified_title', 'Новая заметка')
                content = ai_data.get('beautified_content', '')
                category = ai_data.get('category', 'Мысль')
                event_time_iso = ai_data.get('event_datetime_iso')

                # ОТЧЕТ О СОЗДАНИИ ЗАМЕТКИ В NOTION
                try:
                    create_notion_page(title, content, category)
                    feedback_text = (f"✅ *Заметка в Notion создана!*\n\n*Название:* {title}\n*Категория:* {category}")
                    send_telegram_message(chat_id, feedback_text)
                except Exception as e:
                    error_text = f"❌ *Ошибка при создании заметки в Notion:*\n`{e}`"
                    send_telegram_message(chat_id, error_text)
                    print(f"Ошибка при создании страницы в Notion: {e}")

                # ОТЧЕТ О СОЗДАНИИ СОБЫТИЯ В КАЛЕНДАРЕ
                if event_time_iso:
                    try:
                        create_google_calendar_event(title, content, event_time_iso)
                        dt_object = datetime.fromisoformat(event_time_iso)
                        months_map = {1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля', 5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа', 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'}
                        formatted_date = f"{dt_object.day} {months_map[dt_object.month]} {dt_object.year} в {dt_object.strftime('%H:%M')}"
                        feedback_text = (f"📅 *Событие в Календарь добавлено!*\n\n*Название:* {title}\n*Когда:* {formatted_date}")
                        send_telegram_message(chat_id, feedback_text)
                    except Exception as e:
                        error_text = f"❌ *Ошибка при создании события в Календаре:*\n`{e}`"
                        send_telegram_message(chat_id, error_text)
                        print(f"Ошибка при создании события в Google Calendar: {e}")

        except Exception as e:
            if chat_id:
                send_telegram_message(chat_id, f"🤯 *Произошла глобальная ошибка!*\nПожалуйста, проверьте логи Vercel.\n`{e}`")
            print(f"Произошла глобальная ошибка: {e}")
        
        self.send_response(200)
        self.end_headers()
        return
