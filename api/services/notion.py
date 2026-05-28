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
    return response.json().get('results', [])


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
    """Получает все текстовое содержимое со страницы Notion как Markdown."""
    url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}', 
        'Notion-Version': '2026-03-11'
    }
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json().get('markdown', '')


def create_notion_page(title: str, formatted_content: str, category: str) -> str:
    """Создает страницу в Notion с помощью Markdown API и отправляет её в Pinecone."""
    # Import here to avoid circular dependency
    from services.pinecone_svc import upsert_to_pinecone
    
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
    
    response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    page_id = response.json()['id']
    print(f"Страница {page_id} успешно создана в Notion через Markdown API.")

    try:
        full_text_for_embedding = f"Заголовок: {title}\nСодержимое: {formatted_content}"
        upsert_to_pinecone(page_id, full_text_for_embedding)
    except Exception as e:
        print(f"ОШИБКА ИНДЕКСАЦИИ В PINECONE: {e}")
        
    return page_id


def delete_notion_page(page_id: str):
    """Перемещает страницу в корзину (удаляет) в Notion."""
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


def restore_notion_page(page_id: str):
    """Восстанавливает страницу из корзины в Notion."""
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


def add_to_notion_page(page_id: str, text_to_add: str):
    """Добавляет новый текст в конец страницы с помощью Markdown API."""
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


def add_image_to_page(page_id: str, image_url: str, caption: str = None):
    """Добавляет изображение в конец страницы в виде Markdown-разметки."""
    caption_str = caption or "Изображение"
    image_markdown = f"\n\n![{caption_str}]({image_url})"
    add_to_notion_page(page_id, image_markdown)


def get_page_title(page_id: str) -> str:
    """Получает заголовок страницы Notion по её ID."""
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


def rename_page(page_id: str, new_title: str):
    """Переименовывает страницу Notion."""
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
