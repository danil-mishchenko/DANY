# -*- coding: utf-8 -*-
"""Сервис для работы с Telegram API."""
import json
import io
import requests

from utils.config import TELEGRAM_TOKEN, DEFAULT_TIMEOUT


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


def send_telegram_message(chat_id: str, text: str, use_html: bool = False, add_undo_button: bool = False):
    """Отправляет текстовое сообщение пользователю, опционально с кнопкой 'Отменить'."""
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

    try:
        requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()
    except Exception as e:
        print(f"Ошибка при отправке сообщения в Telegram: {e}")


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
        requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()
    except Exception as e:
        print(f"Ошибка при редактировании сообщения: {e}")
