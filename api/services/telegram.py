# -*- coding: utf-8 -*-
"""Сервис для работы с Telegram API."""
import json
import io
import requests

from utils.config import TELEGRAM_TOKEN, DEFAULT_TIMEOUT


def get_persistent_keyboard():
    """Возвращает структуру постоянной клавиатуры под полем ввода."""
    return {
        "keyboard": [
            [{"text": "📝 Заметки"}, {"text": "🔍 Поиск"}, {"text": "🎙 Транскрипт"}],
            [{"text": "📋 ClickUp"}, {"text": "⚙️ Настройки"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def download_telegram_file(file_id: str) -> io.BytesIO:
    """Загружает файл (голосовое сообщение) с серверов Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
    response = requests.get(url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if 'result' not in data or 'file_path' not in data['result']:
        raise ValueError(f"Не удалось получить путь к файлу: {data}")
    file_path = data['result']['file_path']
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    file_response = requests.get(file_url, timeout=DEFAULT_TIMEOUT)
    file_response.raise_for_status()
    return io.BytesIO(file_response.content)


def get_telegram_file_url(file_id: str) -> str:
    """Получает публичный URL файла из Telegram.
    
    Используется для прикрепления изображений к Notion через external URL.
    URL действителен ~1 час.
    
    Returns:
        Публичный HTTPS URL файла
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
    response = requests.get(url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    
    if 'result' not in data or 'file_path' not in data['result']:
        raise ValueError(f"Не удалось получить путь к файлу: {data}")
    
    file_path = data['result']['file_path']
    return f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"


def send_telegram_message(chat_id: str, text: str, use_html: bool = False, add_undo_button: bool = False, show_keyboard: bool = False, reply_to_message_id: int = None):
    """Отправляет текстовое сообщение пользователю.
    
    Args:
        chat_id: ID чата
        text: Текст сообщения
        use_html: Использовать HTML вместо Markdown
        add_undo_button: Добавить inline-кнопку "Отменить"
        show_keyboard: Показать постоянную клавиатуру
        reply_to_message_id: ID сообщения, на которое нужно ответить
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML' if use_html else 'Markdown'
    }

    if add_undo_button:
        keyboard = {
            "inline_keyboard": [[
                {"text": "↩️ Отменить", "callback_data": "undo_last_action"}
            ]]
        }
        payload['reply_markup'] = json.dumps(keyboard)
    elif show_keyboard:
        payload['reply_markup'] = json.dumps(get_persistent_keyboard())
        
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id

    try:
        requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()
    except Exception as e:
        print(f"Ошибка при отправке сообщения в Telegram: {e}")


def send_message_with_buttons(chat_id: str, text: str, inline_buttons: list, use_html: bool = False, reply_to_message_id: int = None):
    """Отправляет сообщение с inline-кнопками.
    
    Args:
        chat_id: ID чата
        text: Текст сообщения
        inline_buttons: Список рядов кнопок, например:
            [[{"text": "Кнопка 1", "callback_data": "action1"}]]
        use_html: Использовать HTML вместо Markdown
        reply_to_message_id: ID сообщения, на которое нужно ответить
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML' if use_html else 'Markdown',
        'reply_markup': json.dumps({"inline_keyboard": inline_buttons})
    }
    
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id

    try:
        requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()
    except Exception as e:
        print(f"Ошибка при отправке сообщения с кнопками: {e}")


def send_initial_status_message(chat_id: str, text: str):
    """Отправляет начальное сообщение и возвращает его ID для последующего редактирования."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    try:
        response = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        return response.json()['result']['message_id']
    except Exception as e:
        print(f"Ошибка при отправке начального сообщения: {e}")
        return None


def edit_telegram_message(chat_id: str, message_id: int, new_text: str, use_html: bool = False, add_undo_button: bool = False, inline_buttons: list = None):
    """Редактирует существующее сообщение в Telegram.
    
    Args:
        chat_id: ID чата
        message_id: ID сообщения для редактирования
        new_text: Новый текст сообщения
        use_html: Использовать HTML вместо Markdown
        add_undo_button: Добавить только кнопку "Отменить" (устаревший параметр)
        inline_buttons: Список рядов inline-кнопок (приоритетнее add_undo_button)
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': new_text,
        'parse_mode': 'HTML' if use_html else 'Markdown'
    }
    
    if inline_buttons:
        payload['reply_markup'] = json.dumps({"inline_keyboard": inline_buttons})
    elif add_undo_button:
        keyboard = {"inline_keyboard": [[{"text": "↩️ Отменить", "callback_data": "undo_last_action"}]]}
        payload['reply_markup'] = json.dumps(keyboard)
    
    try:
        requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()
    except Exception as e:
        print(f"Ошибка при редактировании сообщения: {e}")


def answer_callback_query(callback_query_id: str, text: str = None):
    """Отвечает на callback query (убирает 'часики' на кнопке)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    payload = {'callback_query_id': callback_query_id}
    if text:
        payload['text'] = text
    try:
        requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
    except Exception as e:
        print(f"Ошибка при ответе на callback: {e}")

