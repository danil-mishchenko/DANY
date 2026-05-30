# -*- coding: utf-8 -*-
"""Сервис для работы с Notion API на базе Notion-Version: 2026-03-11."""
import os
import requests
from datetime import datetime

from utils.config import (
    NOTION_TOKEN, 
    NOTION_DATABASE_ID, 
    DEFAULT_TIMEOUT,
    CATEGORY_EMOJI_MAP
)

# Глобальный кэш для ID источника данных (Data Source ID)
_data_source_id_cache = None


def format_notion_uuid(uuid_str: str) -> str:
    """Приводит 32-символьный ID страницы Notion к стандартному формату с дефисами (8-4-4-4-12)."""
    if not uuid_str:
        return uuid_str
    clean = uuid_str.replace('-', '').strip()
    if len(clean) == 32:
        return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
    return uuid_str


def get_data_source_id() -> str:
    """Определяет ID источника данных для базы данных Notion (с кэшированием).
    
    В Notion API версии 2025-09-03 и новее базы данных являются контейнерами,
    а сами запросы (query) выполняются через /v1/data_sources/{data_source_id}/query.
    """
    global _data_source_id_cache
    if _data_source_id_cache:
        return _data_source_id_cache
        
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Notion-Version': '2026-03-11'
    }
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    data_sources = data.get('data_sources', [])
    if data_sources:
        _data_source_id_cache = data_sources[0]['id']
        return _data_source_id_cache
    else:
        raise ValueError(f"Не найден источник данных (data source) для базы: {NOTION_DATABASE_ID}")


def get_latest_notes(limit: int = 5):
    """Запрашивает у Notion последние N страниц из основной базы данных."""
    from utils.config import ALLOWED_TELEGRAM_ID
    from services.state import get_notes_cache, set_notes_cache
    
    if limit <= 5 and ALLOWED_TELEGRAM_ID:
        try:
            cached_notes = get_notes_cache(ALLOWED_TELEGRAM_ID)
            if cached_notes and len(cached_notes) >= limit:
                print(f"[notion.py] Cache HIT for get_latest_notes(limit={limit})")
                return cached_notes[:limit]
        except Exception as cache_err:
            print(f"[notion.py] Error reading notes cache: {cache_err}")

    ds_id = get_data_source_id()
    url = f"https://api.notion.com/v1/data_sources/{ds_id}/query"
    payload = {
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": limit
    }
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    results = response.json().get('results', [])
    
    if limit >= 5 and ALLOWED_TELEGRAM_ID:
        try:
            set_notes_cache(ALLOWED_TELEGRAM_ID, results)
            print(f"[notion.py] Cached {len(results)} notes in Redis.")
        except Exception as cache_err:
            print(f"[notion.py] Error writing notes cache: {cache_err}")
            
    return results


def search_notion_pages(query: str):
    """Ищет страницы по содержимому в нашей базе данных с помощью фильтра."""
    ds_id = get_data_source_id()
    url = f"https://api.notion.com/v1/data_sources/{ds_id}/query"
    payload = {
        "filter": {
            "property": "Содержание",
            "rich_text": {"contains": query}
        },
        "page_size": 5
    }
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json().get('results', [])


def get_notion_page_content(page_id: str) -> str:
    """Получает все текстовое содержимое со страницы Notion как Markdown (с перманентным кэшированием в Redis)."""
    page_id = format_notion_uuid(page_id)
    
    # Пытаемся получить из кэша Redis
    try:
        from services.state import get_note_content_cache, set_note_content_cache
        cached_content = get_note_content_cache(page_id)
        if cached_content is not None:
            print(f"[notion.py] Cache HIT для контента страницы {page_id}")
            return cached_content
    except Exception as cache_err:
        print(f"[notion.py] Ошибка чтения перманентного кэша: {cache_err}")

    url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Notion-Version': '2026-03-11'
    }
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    markdown_content = response.json().get('markdown', '')
    
    # Сохраняем в кэш Redis
    try:
        set_note_content_cache(page_id, markdown_content)
    except Exception as cache_err:
        print(f"[notion.py] Ошибка записи в перманентный кэш: {cache_err}")
        
    return markdown_content



def create_notion_page(title: str, formatted_content: str, category: str) -> str:
    """Создает страницу в Notion с помощью Markdown API и отправляет её в Pinecone."""
    # Import here to avoid circular dependency
    from services.pinecone_svc import upsert_parent_child_chunks
    
    url = 'https://api.notion.com/v1/pages'
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    page_icon = CATEGORY_EMOJI_MAP.get(category, "📄")
    searchable_content = formatted_content[:2000]
    
    # Свойства страницы (метаданные)
    properties = {
        'Name': {'title': [{'type': 'text', 'text': {'content': title}}]}, 
        'Категория': {'select': {'name': category}}, 
        'Содержание': {'rich_text': [{'type': 'text', 'text': {'content': searchable_content}}]}
    }
    
    payload = {
        'parent': {'database_id': NOTION_DATABASE_ID}, 
        'icon': {'type': 'emoji', 'emoji': page_icon}, 
        'properties': properties, 
        'markdown': formatted_content
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=(3.0, 5.0))
    response.raise_for_status()
    page_id = response.json()['id']
    print(f"Страница {page_id} успешно создана в Notion через Markdown API.")

    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        from services.state import invalidate_notes_cache, set_note_content_cache, set_note_metadata
        if ALLOWED_TELEGRAM_ID:
            invalidate_notes_cache(ALLOWED_TELEGRAM_ID)
        # Сохраняем в кэш Redis
        set_note_content_cache(page_id, formatted_content)
        
        # Сохраняем метаданные в Redis
        import pytz
        from utils.config import USER_TIMEZONE
        tz = pytz.timezone(USER_TIMEZONE)
        now_str = datetime.now(tz).isoformat()
        
        meta = {
            'title': title,
            'category': category,
            'created_time': now_str,
            'last_edited_time': now_str
        }
        set_note_metadata(page_id, meta)
    except Exception as cache_err:
        print(f"Ошибка записи кэша при создании: {cache_err}")

    try:
        import threading
        t = threading.Thread(target=upsert_parent_child_chunks, args=(page_id, title, formatted_content))
        t.daemon = True
        t.start()
        t.join(timeout=0.2)  # Ждем максимум 0.2 секунды
    except Exception as e:
        print(f"ОШИБКА ИНДЕКСАЦИИ В PINECONE: {e}")
        
    return page_id


def delete_notion_page(page_id: str):
    """Перемещает страницу в корзину (удаляет) в Notion."""
    page_id = format_notion_uuid(page_id)
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    payload = {'in_trash': True}
    response = requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    print(f"Страница Notion {page_id} удалена (перемещена в корзину).")
    
    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        from services.state import invalidate_notes_cache, delete_note_content_cache, delete_note_metadata
        if ALLOWED_TELEGRAM_ID:
            invalidate_notes_cache(ALLOWED_TELEGRAM_ID)
        # Удаляем из кэша Redis
        delete_note_content_cache(page_id)
        delete_note_metadata(page_id)
    except Exception as cache_err:
        print(f"Ошибка обновления кэша при удалении: {cache_err}")


def restore_notion_page(page_id: str):
    """Восстанавливает страницу из корзины в Notion."""
    page_id = format_notion_uuid(page_id)
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    payload = {'in_trash': False}
    response = requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    print(f"Страница Notion {page_id} восстановлена из корзины.")
    
    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        from services.state import invalidate_notes_cache, delete_note_content_cache, delete_note_metadata
        if ALLOWED_TELEGRAM_ID:
            invalidate_notes_cache(ALLOWED_TELEGRAM_ID)
        # Сбрасываем кэш контента
        delete_note_content_cache(page_id)
        delete_note_metadata(page_id)
    except Exception as cache_err:
        print(f"Ошибка обновления кэша при восстановлении: {cache_err}")


def add_to_notion_page(page_id: str, text_to_add: str):
    """Добавляет новый текст в конец страницы с помощью Markdown API."""
    page_id = format_notion_uuid(page_id)
    url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    
    payload = {
        "type": "insert_content",
        "insert_content": {
            "content": f"\n\n{text_to_add}",
            "position": {
                "type": "end"
            }
        }
    }
    response = requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    print(f"Текст успешно добавлен в конец страницы {page_id} через Markdown API.")
    
    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        from services.state import invalidate_notes_cache, delete_note_content_cache
        if ALLOWED_TELEGRAM_ID:
            invalidate_notes_cache(ALLOWED_TELEGRAM_ID)
        # Сбрасываем кэш контента
        delete_note_content_cache(page_id)
    except Exception as cache_err:
        print(f"Ошибка обновления кэша при добавлении: {cache_err}")


def add_image_to_page(page_id: str, image_url: str, caption: str = None):
    """Добавляет изображение в конец страницы в виде Markdown-разметки."""
    caption_str = caption or "Изображение"
    image_markdown = f"\n\n![{caption_str}]({image_url})"
    add_to_notion_page(page_id, image_markdown)


def get_page_title(page_id: str) -> str:
    """Получает заголовок страницы Notion по её ID."""
    page_id = format_notion_uuid(page_id)
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Notion-Version': '2026-03-11'
    }
    
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
    """Получает превью страницы: заголовок + первые N символов контента."""
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


def replace_page_content(page_id: str, new_content: str):
    """Заменяет весь контент страницы на новый атомарно через Markdown API."""
    page_id = format_notion_uuid(page_id)
    url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    
    payload = {
        "type": "replace_content",
        "replace_content": {
            "new_str": new_content,
            "allow_deleting_content": True
        }
    }
    response = requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    print(f"Контент страницы {page_id} успешно атомарно перезаписан через Markdown API.")
    
    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        from services.state import invalidate_notes_cache, set_note_content_cache, get_note_metadata, set_note_metadata
        if ALLOWED_TELEGRAM_ID:
            invalidate_notes_cache(ALLOWED_TELEGRAM_ID)
        # Записываем новый контент в кэш
        set_note_content_cache(page_id, new_content)
        
        # Обновляем last_edited_time в метаданных Redis
        import pytz
        from utils.config import USER_TIMEZONE
        tz = pytz.timezone(USER_TIMEZONE)
        now_str = datetime.now(tz).isoformat()
        
        meta = get_note_metadata(page_id)
        if meta:
            meta['last_edited_time'] = now_str
        else:
            meta = {
                'title': get_page_title(page_id),
                'category': 'Мысль',
                'created_time': now_str,
                'last_edited_time': now_str
            }
        set_note_metadata(page_id, meta)
    except Exception as cache_err:
        print(f"Ошибка обновления кэша при замене контента: {cache_err}")
        
    try:
        # Также обновляем вектор в Pinecone в фоне!
        from services.pinecone_svc import upsert_parent_child_chunks
        title = get_page_title(page_id)
        import threading
        t = threading.Thread(target=upsert_parent_child_chunks, args=(page_id, title, new_content))
        t.daemon = True
        t.start()
        t.join(timeout=0.2)
    except Exception as pe:
        print(f"Ошибка обновления вектора при замене контента: {pe}")


def rename_page(page_id: str, new_title: str):
    """Переименовывает страницу Notion."""
    page_id = format_notion_uuid(page_id)
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Content-Type': 'application/json', 
        'Notion-Version': '2026-03-11'
    }
    payload = {
        'properties': {
            'Name': {'title': [{'type': 'text', 'text': {'content': new_title}}]}
        }
    }
    response = requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    print(f"Страница {page_id} переименована в '{new_title}'")
    
    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        from services.state import invalidate_notes_cache
        if ALLOWED_TELEGRAM_ID:
            invalidate_notes_cache(ALLOWED_TELEGRAM_ID)
    except Exception as cache_err:
        print(f"Ошибка инвалидации кэша при переименовании: {cache_err}")
