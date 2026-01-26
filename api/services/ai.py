# -*- coding: utf-8 -*-
"""Сервис для работы с AI (OpenAI, AssemblyAI)."""
import json
import time
import requests

from utils.config import (
    OPENAI_API_KEY, 
    ASSEMBLYAI_API_KEY, 
    DEFAULT_TIMEOUT, 
    MAX_POLLING_ATTEMPTS
)


def transcribe_with_assemblyai(audio_file_bytes) -> str:
    """Отправляет аудио в AssemblyAI и получает результат."""
    headers = {'authorization': ASSEMBLYAI_API_KEY}

    # 1. Отправляем файл на сервер AssemblyAI
    upload_response = requests.post(
        'https://api.assemblyai.com/v2/upload',
        headers=headers,
        data=audio_file_bytes,
        timeout=DEFAULT_TIMEOUT
    )
    upload_response.raise_for_status()
    audio_url = upload_response.json()['upload_url']
    print("Аудиофайл успешно загружен в AssemblyAI.")

    # 2. Запускаем задачу транскрибации
    transcript_request = {'audio_url': audio_url, 'language_code': 'ru'}
    transcript_response = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        json=transcript_request,
        headers=headers,
        timeout=DEFAULT_TIMEOUT
    )
    transcript_response.raise_for_status()
    transcript_id = transcript_response.json()['id']
    print(f"Задача на транскрибацию создана с ID: {transcript_id}")

    # 3. Ждем результата с ограничением по времени
    for attempt in range(MAX_POLLING_ATTEMPTS):
        polling_response = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
            headers=headers,
            timeout=DEFAULT_TIMEOUT
        )
        polling_response.raise_for_status()
        status = polling_response.json()['status']
        if status == 'completed':
            print("Транскрибация завершена.")
            return polling_response.json()['text']
        elif status == 'error':
            print("Ошибка транскрибации в AssemblyAI.")
            return None
        time.sleep(2)
    
    print(f"Превышено время ожидания транскрибации после {MAX_POLLING_ATTEMPTS} попыток")
    return None


def process_with_ai(text: str) -> dict:
    """Отправляет текст в GPT-4o mini для умного форматирования и извлечения данных."""
    from datetime import datetime
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
    
    current_datetime_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    prompt = f"""
    Твоя роль: умный редактор заметок. Проанализируй заметку пользователя. Текущее время для расчетов: {current_datetime_str}.
    
    Задачи:
    1. Язык: Сохраняй язык оригинала. Не переводи.
    2. Заголовок и Категория: Создай емкий заголовок и определи категорию из списка: [Идея, Задача, Покупка, Встреча, Мысль, Ссылка, Цитата].
    3. Форматирование:
        - Используй Markdown: **жирный** для ключевых слов и заголовков (можно с 1 эмодзи)
        - Списки — через дефис с эмодзи
        - Комментарии — *курсивом*
        - Разбивай текст на короткие смысловые блоки (макс. 3-4 строки)
        - Структурируй: сначала суть, потом детали
        - Используй разделители --- между крупными темами
        - Не пиши «стеной текста», делай заметки лёгкими для чтения
        - ВАЖНО: Каждую ссылку (URL) размещай на отдельной строке
        - Убирай явное пустословие, оптимизируй
    4. Если есть обращение к ассистенту (также ИИ, бот и тд.) — воспринимай как поправку к промпту.
    5. События: Найди ВСЕ события с датой/временем. Учитывай относительные даты ("завтра", "через 30 минут"). Если их нет — верни пустой список "events": [].
    6. Результат: Верни строго JSON.
    
    Формат JSON: {{"main_title": "...", "category": "...", "formatted_body": "...", "events": [{{"title": "...", "datetime_iso": "..."}}]}}
    
    Заметка:
    ---
    {text}
    ---
    """
    data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
    response = requests.post(url, headers=headers, json=data, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    ai_response = response.json()
    # Валидация ответа AI
    if not ai_response.get('choices') or not ai_response['choices'][0].get('message'):
        raise ValueError("Невалидный ответ от OpenAI API")
    return json.loads(ai_response['choices'][0]['message']['content'])


def summarize_for_search(context: str, question: str) -> str:
    """Отправляет контекст и вопрос в GPT-4o mini для генерации ответа."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
    prompt = f"""
    Основываясь СТРОГО на предоставленном ниже тексте из заметки, дай краткий и четкий ответ на вопрос пользователя. Не выдумывай ничего. Если в тексте нет ответа, сообщи об этом. Ответ должен быть красиво оформлен, а нужные блоки текста выделенны цитатой.
    
    Текст заметки:
    ---
    {context}
    ---
    Вопрос пользователя: "{question}"
    """
    data = {"model": "gpt-4o-mini", "messages": [{"role": "system", "content": "Ты — полезный ассистент, отвечающий на вопросы по тексту."}, {"role": "user", "content": prompt}]}
    response = requests.post(url, headers=headers, json=data, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def polish_content(old_content: str, new_content: str) -> str:
    """Объединяет и полирует контент через AI.
    
    Лёгкая полировка: исправление опечаток, улучшение форматирования,
    объединение в единый текст без изменения смысла.
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
    
    prompt = f"""
    Объедини два текста в один красивый и логичный. Выполни ЛЁГКУЮ полировку:
    - Исправь опечатки
    - Улучши форматирование (списки, заголовки с эмодзи)
    - Убери повторы и пустословие
    - НЕ меняй смысл и НЕ добавляй новую информацию
    - Сохраняй язык оригинала
    
    Существующий текст:
    ---
    {old_content}
    ---
    
    Новый текст для добавления:
    ---
    {new_content}
    ---
    
    Верни ТОЛЬКО отполированный текст, без комментариев.
    """
    
    data = {
        "model": "gpt-4o-mini", 
        "messages": [
            {"role": "system", "content": "Ты — редактор заметок. Полируешь текст, сохраняя смысл."},
            {"role": "user", "content": prompt}
        ]
    }
    
    response = requests.post(url, headers=headers, json=data, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']
