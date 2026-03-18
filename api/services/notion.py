# -*- coding: utf-8 -*-
"""Сервис для работы с Notion API."""
import os
import requests
from datetime import datetime

from utils.config import (
    NOTION_TOKEN, 
    NOTION_DATABASE_ID, 
    NOTION_LOG_DB_ID,
    GOOGLE_CALENDAR_ID,
    DEFAULT_TIMEOUT,
    CATEGORY_EMOJI_MAP
)
from utils.markdown import parse_to_notion_blocks


def get_latest_notes(limit: int = 5):
    """Запрашивает у Notion последние N страниц из основной базы данных."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": limit
    }
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json().get('results', [])


def search_notion_pages(query: str):
    """Ищет страницы по содержимому в нашей базе данных с помощью фильтра."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "Содержание",
            "rich_text": {"contains": query}
        },
        "page_size": 5
    }
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json().get('results', [])


def get_notion_page_content(page_id: str) -> str:
    """Получает все текстовое содержимое со страницы Notion."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    blocks = response.json().get('results', [])
    
    content = []
    for block in blocks:
        block_type = block['type']
        if block_type in ['paragraph', 'bulleted_list_item', 'heading_1', 'heading_2', 'heading_3']:
            rich_text_array = block.get(block_type, {}).get('rich_text', [])
            for rich_text in rich_text_array:
                content.append(rich_text.get('plain_text', ''))
        elif block_type == 'code':
            rich_text_array = block.get('code', {}).get('rich_text', [])
            for rich_text in rich_text_array:
                content.append(rich_text.get('plain_text', ''))

    return "\n".join(content)


def create_notion_page(title: str, formatted_content: str, category: str):
    """Создает страницу в Notion и отправляет ее контент на индексацию в Pinecone."""
    # Import here to avoid circular dependency
    from services.pinecone_svc import upsert_to_pinecone
    
    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    page_icon = CATEGORY_EMOJI_MAP.get(category, "📄")
    searchable_content = formatted_content[:2000]
    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': title}}]}, 
        'Категория': {'select': {'name': category}}, 
        'Содержание': {'rich_text': [{'type': 'text', 'text': {'content': searchable_content}}]}
    }
    children = parse_to_notion_blocks(formatted_content)
    payload = {
        'parent': {'database_id': NOTION_DATABASE_ID}, 
        'icon': {'type': 'emoji', 'emoji': page_icon}, 
        'properties': properties, 
        'children': children
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    page_id = response.json()['id']
    print(f"Страница {page_id} успешно создана в Notion.")

    try:
        full_text_for_embedding = f"Заголовок: {title}\nСодержимое: {formatted_content}"
        upsert_to_pinecone(page_id, full_text_for_embedding)
    except Exception as e:
        print(f"ОШИБКА ИНДЕКСАЦИИ В PINECONE: {e}")
        
    return page_id


def delete_notion_page(page_id):
    """Архивирует (удаляет) страницу в Notion."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    payload = {'archived': True}
    requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    print(f"Страница Notion {page_id} удалена.")


def restore_notion_page(page_id):
    """Восстанавливает (разархивирует) страницу в Notion."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {'archived': False}
    requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    print(f"Страница Notion {page_id} восстановлена.")


def add_to_notion_page(page_id: str, text_to_add: str):
    """Добавляет новые блоки текста в конец страницы Notion."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    new_blocks = parse_to_notion_blocks(text_to_add)
    payload = {'children': new_blocks}
    requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()


def add_image_to_page(page_id: str, image_url: str, caption: str = None):
    """Добавляет изображение в конец страницы Notion.
    
    Args:
        page_id: ID страницы Notion
        image_url: Публичный HTTPS URL изображения
        caption: Опциональная подпись к изображению
    """
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2022-06-28'
    }
    
    image_block = {
        "object": "block",
        "type": "image",
        "image": {
            "type": "external",
            "external": {"url": image_url}
        }
    }
    
    if caption:
        image_block["image"]["caption"] = [{"type": "text", "text": {"content": caption}}]
    
    payload = {"children": [image_block]}
    requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()


def get_last_created_page_id():
    """Получает ID последней созданной страницы из лога действий.
    
    Ищет записи с непустым NotionPageID и пустым State (т.е. это создание заметки, а не состояние).
    """
    log_db_id = NOTION_LOG_DB_ID
    if not log_db_id:
        return None
    
    query_url = f"https://api.notion.com/v1/databases/{log_db_id}/query"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {
        "filter": {
            "and": [
                {"property": "NotionPageID", "rich_text": {"is_not_empty": True}},
                {"property": "State", "select": {"is_empty": True}}
            ]
        },
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 1
    }
    
    response = requests.post(query_url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    results = response.json().get('results', [])
    
    if not results:
        return None
    
    properties = results[0]['properties']
    notion_page_id = properties.get('NotionPageID', {}).get('rich_text', [])
    if notion_page_id:
        return notion_page_id[0]['text']['content']
    return None


def get_page_title(page_id: str) -> str:
    """Получает заголовок страницы Notion по её ID."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    
    try:
        response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        properties = response.json().get('properties', {})
        title_prop = properties.get('Name', {}).get('title', [])
        if title_prop:
            return title_prop[0].get('plain_text', 'Без названия')
    except Exception as e:
        print(f"Ошибка получения заголовка страницы {page_id}: {e}")
    
    return "Без названия"


def get_page_preview(page_id: str, max_chars: int = 100) -> dict:
    """Получает превью страницы: заголовок + первые N символов контента.
    
    Returns:
        dict с ключами: title, preview, page_id
    """
    title = get_page_title(page_id)
    content = get_notion_page_content(page_id)
    
    if len(content) > max_chars:
        preview = content[:max_chars].strip() + "..."
    else:
        preview = content
    
    return {
        'title': title,
        'preview': preview,
        'page_id': page_id
    }


def get_page_blocks(page_id: str) -> list:
    """Получает все блоки страницы Notion (для удаления/замены)."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json().get('results', [])


def delete_block(block_id: str):
    """Удаляет блок в Notion."""
    url = f"https://api.notion.com/v1/blocks/{block_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    requests.delete(url, headers=headers, timeout=DEFAULT_TIMEOUT)


def replace_page_content(page_id: str, new_content: str):
    """Заменяет весь контент страницы на новый (для полировки).
    
    1. Удаляет все существующие блоки
    2. Добавляет новые блоки из new_content
    """
    # 1. Получаем и удаляем все блоки
    blocks = get_page_blocks(page_id)
    for block in blocks:
        try:
            delete_block(block['id'])
        except Exception as e:
            print(f"Ошибка удаления блока {block['id']}: {e}")
    
    # 2. Добавляем новый контент
    add_to_notion_page(page_id, new_content)


def rename_page(page_id: str, new_title: str):
    """Переименовывает страницу Notion."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {
        'properties': {
            'Name': {'title': [{'type': 'text', 'text': {'content': new_title}}]}
        }
    }
    response = requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    print(f"Страница {page_id} переименована в '{new_title}'")


def get_and_delete_last_log():
    """Получает последнюю запись из лога, извлекает данные и удаляет запись."""
    log_db_id = NOTION_LOG_DB_ID
    if not log_db_id:
        return None

    query_url = f"https://api.notion.com/v1/databases/{log_db_id}/query"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 1
    }
    response = requests.post(query_url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    results = response.json().get('results', [])

    if not results:
        print("Лог действий пуст.")
        return None

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
    
    delete_notion_page(log_page_id)
    
    print(f"Получены и удалены детали последнего действия: {action_details}")
    return action_details


def log_last_action(properties: dict = None, notion_page_id: str = None, gcal_event_id: str = None):
    """Записывает действие или состояние в лог-базу Notion."""
    log_db_id = NOTION_LOG_DB_ID
    if not log_db_id:
        print("ОШИБКА ЛОГИРОВАНИЯ: Переменная NOTION_LOG_DB_ID не найдена.")
        return

    if properties is None:
        properties = {
            'Name': {'title': [{'type': 'text', 'text': {'content': f"Action at {datetime.now()}"}}]},
            'NotionPageID': {'rich_text': [{'type': 'text', 'text': {'content': notion_page_id or ""}}]},
            'GCalEventID': {'rich_text': [{'type': 'text', 'text': {'content': gcal_event_id or ""}}]},
            'GCalCalendarID': {'rich_text': [{'type': 'text', 'text': {'content': GOOGLE_CALENDAR_ID or ""}}]}
        }

    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {'parent': {'database_id': log_db_id}, 'properties': properties}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        print(f"Действие успешно залогировано: {properties.get('Name', {}).get('title', [{}])[0].get('text', {}).get('content')}")
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА ЛОГИРОВАНИЯ: {e}")


def set_user_state(user_id: str, state: str, page_id: str, pending_edit_text: str = None):
    """Создает запись о намерении пользователя в лог-базе.
    
    Args:
        user_id: ID пользователя Telegram
        state: Тип состояния (awaiting_add_text, awaiting_rename, pending_edit, etc.)
        page_id: ID страницы Notion для операции
        pending_edit_text: Текст, который нужно добавить (для pending_edit)
    """
    if state is None:
        # Очистка состояния - удаляем последнюю запись состояния
        return
    
    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': f"State for {user_id}: {state}"}}]},
        'UserID': {'rich_text': [{'type': 'text', 'text': {'content': user_id}}]},
        'NotionPageID': {'rich_text': [{'type': 'text', 'text': {'content': page_id or ''}}]},
        'State': {'select': {'name': state}}
    }
    
    # Храним pending_edit_text в GCalEventID поле (переиспользуем для экономии)
    if pending_edit_text:
        properties['GCalEventID'] = {'rich_text': [{'type': 'text', 'text': {'content': pending_edit_text[:2000]}}]}
    
    log_last_action(properties=properties)


def get_user_state(user_id: str):
    """Проверяет, есть ли для пользователя активное состояние, и удаляет его."""
    log_db_id = NOTION_LOG_DB_ID
    if not log_db_id: 
        return None
    
    payload = {
        "filter": {"and": [
            {"property": "UserID", "rich_text": {"equals": user_id}}, 
            {"property": "State", "select": {"is_not_empty": True}}
        ]},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}], 
        "page_size": 1
    }
    query_url = f"https://api.notion.com/v1/databases/{log_db_id}/query"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    response = requests.post(query_url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    results = response.json().get('results', [])

    if not results: 
        return None
    
    state_page = results[0]
    state_page_id = state_page['id']
    properties = state_page['properties']
    
    def get_text(prop): 
        return prop['rich_text'][0]['text']['content'] if prop.get('rich_text') else None
    
    state_details = {
        'state': properties.get('State', {}).get('select', {}).get('name'),
        'page_id': get_text(properties.get('NotionPageID')),
        'pending_edit_text': get_text(properties.get('GCalEventID'))  # Переиспользуем поле
    }
    delete_notion_page(state_page_id)
    return state_details


# === TEMP TRANSCRIPT STORAGE (Features 1, 2, 6) ===

def save_temp_transcript(user_id: str, text: str) -> str:
    """Сохраняет длинный текст транскрипта во временный лог и возвращает его ID.
    Необходимо для обхода лимита 64 байт в callback_data кнопок Telegram.
    """
    log_db_id = NOTION_LOG_DB_ID
    if not log_db_id:
        return None

    url = 'https://api.notion.com/v1/pages'
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    
    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': f"Temp Transcript for {user_id}"}}]},
        'UserID': {'rich_text': [{'type': 'text', 'text': {'content': str(user_id)}}]},
        'State': {'select': {'name': 'temp_transcript'}}
    }
    
    payload = {'parent': {'database_id': log_db_id}, 'properties': properties}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        log_id = response.json()['id']
        
        # Записываем длинный текст блоком (может быть > 2000 симв)
        add_to_notion_page(log_id, text)
        return log_id
    except Exception as e:
        print(f"Ошибка сохранения временного транскрипта: {e}")
        return None


def get_temp_transcript(log_id: str) -> str:
    """Получает текст временного транскрипта и удаляет запись."""
    if not log_id:
        return None
        
    try:
        content = get_notion_page_content(log_id)
        # Удаляем временную запись после использования
        delete_notion_page(log_id)
        return content
    except Exception as e:
        print(f"Ошибка получения временного транскрипта: {e}")
        return None


def get_transcript_buffer(user_id: str):
    """Возвращает текущий буфер мульти-транскрипта для пользователя."""
    log_db_id = NOTION_LOG_DB_ID
    if not log_db_id: 
        return None, ""
    
    payload = {
        "filter": {"and": [
            {"property": "UserID", "rich_text": {"equals": str(user_id)}}, 
            {"property": "State", "select": {"equals": "transcript_buffer"}}
        ]},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}], 
        "page_size": 1
    }
    query_url = f"https://api.notion.com/v1/databases/{log_db_id}/query"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    
    try:
        response = requests.post(query_url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        results = response.json().get('results', [])
        
        if not results:
            return None, ""
            
        buffer_page_id = results[0]['id']
        content = get_notion_page_content(buffer_page_id)
        return buffer_page_id, content
    except Exception as e:
        print(f"Ошибка получения буфера транскрипта: {e}")
        return None, ""


def append_to_transcript_buffer(user_id: str, new_text: str) -> str:
    """Добавляет текст в буфер мульти-транскрипта. Создаёт, если нужно."""
    buffer_page_id, _ = get_transcript_buffer(user_id)
    
    if not buffer_page_id:
        log_db_id = NOTION_LOG_DB_ID
        url = 'https://api.notion.com/v1/pages'
        headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
        
        properties = {
            'Name': {'title': [{'type': 'text', 'text': {'content': f"Transcript Buffer for {user_id}"}}]},
            'UserID': {'rich_text': [{'type': 'text', 'text': {'content': str(user_id)}}]},
            'State': {'select': {'name': 'transcript_buffer'}}
        }
        
        payload = {'parent': {'database_id': log_db_id}, 'properties': properties}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            buffer_page_id = response.json()['id']
        except Exception as e:
            print(f"Ошибка создания буфера транскрипта: {e}")
            return None

    # Добавляем разделитель и новый текст
    separator = "\n\n---\n\n"
    add_to_notion_page(buffer_page_id, separator + new_text)
    
    # Возвращаем обновленный контент
    return get_notion_page_content(buffer_page_id)


def clear_transcript_buffer(user_id: str):
    """Удаляет буфер мульти-транскрипта."""
    buffer_page_id, _ = get_transcript_buffer(user_id)
    if buffer_page_id:
        delete_notion_page(buffer_page_id)


# === UNIFIED SETTINGS STORAGE ===
# Хранит ВСЕ настройки (reminder, hidden_tasks, XP) в ОДНОЙ Notion странице
# в основной БД заметок. Использует GET /pages/{id} (всегда консистентно),
# а НЕ database query (eventual consistency).

_SETTINGS_PAGE_TITLE = "⚙️ Bot Settings"
_settings_page_id_cache = None  # кеш page_id в рамках одного запроса


def _find_settings_page_id(user_id: str) -> str:
    """Ищет страницу настроек в основной БД заметок по названию.
    
    Возвращает page_id или None.
    """
    global _settings_page_id_cache
    if _settings_page_id_cache:
        return _settings_page_id_cache
    
    db_id = NOTION_DATABASE_ID
    if not db_id:
        return None
    
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    
    # Поиск по названию в основной БД
    payload = {
        "filter": {
            "property": "Name",
            "title": {"equals": _SETTINGS_PAGE_TITLE}
        },
        "page_size": 1
    }
    query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
    
    try:
        response = requests.post(query_url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        results = response.json().get('results', [])
        if results:
            _settings_page_id_cache = results[0]['id']
            return _settings_page_id_cache
    except Exception as e:
        print(f"SETTINGS FIND ERROR: {e}")
    
    return None


def _create_settings_page(user_id: str, settings: dict) -> str:
    """Создаёт страницу настроек в основной БД и возвращает page_id."""
    import json as json_mod
    global _settings_page_id_cache
    
    db_id = NOTION_DATABASE_ID
    if not db_id:
        return None
    
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "Name": {"title": [{"type": "text", "text": {"content": _SETTINGS_PAGE_TITLE}}]}
        },
        "children": [
            {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": json_mod.dumps(settings, ensure_ascii=False)}}],
                    "language": "json"
                }
            }
        ]
    }
    
    try:
        resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            page_id = resp.json()['id']
            _settings_page_id_cache = page_id
            print(f"SETTINGS CREATE: page_id={page_id}")
            return page_id
        else:
            print(f"SETTINGS CREATE ERROR: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"SETTINGS CREATE ERROR: {e}")
    return None


def _read_settings(user_id: str) -> tuple:
    """Читает настройки. Возвращает (page_id, block_id, settings_dict).
    
    Использует GET /blocks/{page_id}/children — всегда консистентно.
    """
    import json as json_mod
    
    page_id = _find_settings_page_id(user_id)
    if not page_id:
        return None, None, {}
    
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    
    try:
        # GET блоки страницы — это ВСЕГДА консистентно (не database query)
        resp = requests.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=5",
            headers=headers,
            timeout=DEFAULT_TIMEOUT
        )
        if resp.status_code != 200:
            print(f"SETTINGS READ ERROR: {resp.status_code}")
            return page_id, None, {}
        
        blocks = resp.json().get('results', [])
        for block in blocks:
            if block.get('type') == 'code':
                text_arr = block['code'].get('rich_text', [])
                if text_arr:
                    raw = text_arr[0]['text']['content']
                    try:
                        settings = json_mod.loads(raw)
                        if isinstance(settings, dict):
                            return page_id, block['id'], settings
                    except (json_mod.JSONDecodeError, ValueError):
                        pass
        
        return page_id, None, {}
    except Exception as e:
        print(f"SETTINGS READ ERROR: {e}")
        return page_id, None, {}


def _write_settings(user_id: str, settings: dict):
    """Записывает настройки через UPDATE block content."""
    import json as json_mod
    
    page_id, block_id, _ = _read_settings(user_id)
    
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    json_content = json_mod.dumps(settings, ensure_ascii=False)
    
    if block_id:
        # UPDATE существующего блока
        try:
            resp = requests.patch(
                f"https://api.notion.com/v1/blocks/{block_id}",
                headers=headers,
                json={
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": json_content}}],
                        "language": "json"
                    }
                },
                timeout=DEFAULT_TIMEOUT
            )
            if resp.status_code == 200:
                print(f"SETTINGS WRITE OK")
            else:
                print(f"SETTINGS WRITE ERROR: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"SETTINGS WRITE ERROR: {e}")
    elif page_id:
        # Страница есть но блока нет — добавляем блок
        try:
            resp = requests.patch(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers=headers,
                json={
                    "children": [{
                        "object": "block",
                        "type": "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": json_content}}],
                            "language": "json"
                        }
                    }]
                },
                timeout=DEFAULT_TIMEOUT
            )
            if resp.status_code == 200:
                print(f"SETTINGS APPEND OK")
            else:
                print(f"SETTINGS APPEND ERROR: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"SETTINGS APPEND ERROR: {e}")
    else:
        # Нет страницы — создаём
        _create_settings_page(user_id, settings)


# --- Public API ---

def get_user_settings(user_id: str) -> dict:
    """Получает настройки пользователя."""
    _, _, settings = _read_settings(user_id)
    if 'reminder_minutes' not in settings:
        settings['reminder_minutes'] = 15
    return settings


def set_user_settings(user_id: str, reminder_minutes: int):
    """Сохраняет reminder_minutes (сохраняя остальные настройки)."""
    _, _, settings = _read_settings(user_id)
    settings['reminder_minutes'] = reminder_minutes
    _write_settings(user_id, settings)


def get_hidden_tasks(user_id: str) -> list:
    """Получает список скрытых задач ClickUp."""
    _, _, settings = _read_settings(user_id)
    return settings.get('hidden_tasks', [])


def set_hidden_tasks(user_id: str, task_ids: list):
    """Сохраняет список скрытых задач."""
    _, _, settings = _read_settings(user_id)
    settings['hidden_tasks'] = task_ids
    _write_settings(user_id, settings)


def add_hidden_task(user_id: str, task_id: str):
    """Добавляет задачу в скрытые."""
    _, _, settings = _read_settings(user_id)
    hidden = settings.get('hidden_tasks', [])
    if task_id not in hidden:
        hidden.append(task_id)
        settings['hidden_tasks'] = hidden
        _write_settings(user_id, settings)
        print(f"HIDDEN: +{task_id}, total={len(hidden)}")


def remove_hidden_task(user_id: str, task_id: str):
    """Убирает задачу из скрытых."""
    _, _, settings = _read_settings(user_id)
    hidden = settings.get('hidden_tasks', [])
    if task_id in hidden:
        hidden.remove(task_id)
        settings['hidden_tasks'] = hidden
        _write_settings(user_id, settings)


def get_user_xp(user_id: str) -> dict:
    """Получает XP пользователя."""
    _, _, settings = _read_settings(user_id)
    return {'xp': settings.get('xp', 0), 'level': settings.get('level', 1)}


def set_user_xp(user_id: str, xp_data: dict):
    """Сохраняет XP пользователя."""
    _, _, settings = _read_settings(user_id)
    settings['xp'] = xp_data.get('xp', 0)
    settings['level'] = xp_data.get('level', 1)
    _write_settings(user_id, settings)


# === ACTIVE MODE ===

def get_active_mode(user_id: str) -> str:
    """Получает текущий активный режим бота (например, 'transcript').
    
    Returns:
        Строка с названием режима или None если обычный режим.
    """
    _, _, settings = _read_settings(user_id)
    return settings.get('active_mode', None)


def set_active_mode(user_id: str, mode: str):
    """Устанавливает активный режим бота.
    
    Args:
        user_id: ID пользователя
        mode: Название режима ('transcript') или None для сброса
    """
    _, _, settings = _read_settings(user_id)
    if mode is None:
        settings.pop('active_mode', None)
    else:
        settings['active_mode'] = mode
    _write_settings(user_id, settings)


# === TRANSCRIPT SETTINGS ===

def get_transcript_clean(user_id: str) -> bool:
    """Возвращает True если включён чистый режим транскрипта (без заполнителей)."""
    _, _, settings = _read_settings(user_id)
    return settings.get('transcript_clean', False)


def set_transcript_clean(user_id: str, clean: bool):
    """Устанавливает подрежим транскрипта (чистый / дословный)."""
    _, _, settings = _read_settings(user_id)
    settings['transcript_clean'] = clean
    _write_settings(user_id, settings)
