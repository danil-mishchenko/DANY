# -*- coding: utf-8 -*-
import os
import json
import requests
import io
import openai
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Секретные ключи и ID из переменных окружения Vercel ---
# Эти переменные мы настроим в панели управления Vercel.
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')

# Инициализируем клиент OpenAI
openai.api_key = OPENAI_API_KEY


# --- 1. Функции для работы с внешними API ---

def download_telegram_file(file_id: str) -> io.BytesIO:
    """Загружает файл (голосовое сообщение) с серверов Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
    response = requests.get(url)
    file_path = response.json()['result']['file_path']
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    file_response = requests.get(file_url)
    return io.BytesIO(file_response.content)

def transcribe_audio_with_whisper(audio_file: io.BytesIO) -> str:
    """Отправляет аудиофайл в OpenAI Whisper для транскрибации."""
    audio_file.name = "voice.oga" # Whisper требует имя файла
    transcript = openai.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
    )
    return transcript.text

def process_with_deepseek(text: str) -> dict:
    """Отправляет текст в DeepSeek для анализа, улучшения и извлечения данных."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    current_date_str = datetime.now().strftime('%Y-%m-%d')
    prompt = f"""
    Проанализируй следующую заметку пользователя, сделанную {current_date_str}. Твоя задача:
    1. Определить наиболее подходящую категорию для этой заметки из списка: [Идея, Задача, Покупка, Встреча, Мысль, Ссылка, Цитата].
    2. Слегка переписать и улучшить текст заметки: исправь опечатки, улучши стиль, сделай заголовок и основной текст более четкими.
    3. Проверить, содержит ли заметка конкретную дату и время. Если да, верни дату и время в формате ISO 8601 для часового пояса Europe/Kyiv. Если время не указано, используй 12:00. Если дата не указана, верни null. Учитывай относительные даты, как "завтра", "в среду".
    4. Верни результат строго в формате JSON, без каких-либо других слов и пояснений.

    Формат JSON:
    {{
      "category": "одна_категория_из_списка",
      "beautified_title": "улучшенный_заголовок_заметки",
      "beautified_content": "улучшенный_основной_текст_заметки" или null,
      "event_datetime_iso": "YYYY-MM-DDTHH:MM:SS" или null
    }}

    Заметка:
    ---
    {text}
    ---
    """

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Ты — умный ассистент-редактор, который помогает пользователю организовывать заметки и планировать события."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "response_format": {"type": "json_object"} # Просим DeepSeek гарантированно вернуть JSON
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def create_notion_page(title: str, content: str, category: str):
    """Создает новую страницу в базе данных Notion."""
    url = 'https://api.notion.com/v1/pages'
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28'
    }
    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': title}}]},
        'Категория': {'select': {'name': category}}
    }
    
    children = []
    if content:
        children.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}
        })

    payload = {'parent': {'database_id': NOTION_DATABASE_ID}, 'properties': properties, 'children': children}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    print("Страница в Notion успешно создана.")


def create_google_calendar_event(title: str, description: str, start_time_iso: str):
    """Создает новое событие в основном Google Календаре."""
    creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(creds_info)
    service = build('calendar', 'v3', credentials=creds)
    
    start_time = datetime.fromisoformat(start_time_iso)
    end_time = start_time + timedelta(hours=1)

    event = {
        'summary': title, 'description': description,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Europe/Kyiv'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Europe/Kyiv'},
    }

    service.events().insert(calendarId='primary', body=event).execute()
    print("Событие в Google Calendar успешно создано.")


# --- 2. Основной обработчик запросов от Telegram ---

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Получаем тело запроса от Telegram
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            update = json.loads(body.decode('utf-8'))

            if 'message' not in update:
                self.send_response(200)
                self.end_headers()
                return

            message = update['message']
            text_to_process = None

            # --- Шаг 1: Получаем текст (либо из сообщения, либо из аудио) ---
            if 'text' in message:
                text_to_process = message['text']
            elif 'voice' in message:
                audio_file_io = download_telegram_file(message['voice']['file_id'])
                text_to_process = transcribe_audio_with_whisper(audio_file_io)

            if not text_to_process:
                self.send_response(200)
                self.end_headers()
                return

            # --- Шаг 2: Анализируем текст с помощью ИИ ---
            ai_result_str = process_with_deepseek(text_to_process)
            ai_data = json.loads(ai_result_str)
            
            title = ai_data.get('beautified_title', 'Новая заметка')
            content = ai_data.get('beautified_content', '')
            category = ai_data.get('category', 'Мысль')
            event_time_iso = ai_data.get('event_datetime_iso')

            # --- Шаг 3: Раскладываем по полочкам (Notion и Google Calendar) ---
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
            # Логируем любую ошибку, чтобы можно было посмотреть в логах Vercel
            print(f"Произошла глобальная ошибка: {e}")
        
        # Всегда отвечаем Telegram "OK", чтобы он не слал повторные запросы
        self.send_response(200)
        self.end_headers()
        return
