# -*- coding: utf-8 -*-
"""Сервис для работы с Notion API."""
import os
import requests
from datetime import datetime
import concurrent.futures


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
    
    # Лимит Notion API на количество блоков в одном запросе равен 100.
    # Разбиваем блоки на пачки по 100 для надежной и эффективной вставки.
    chunk_size = 100
    for i in range(0, len(new_blocks), chunk_size):
        chunk = new_blocks[i:i + chunk_size]
        payload = {'children': chunk}
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
    """Получает все блоки страницы Notion с поддержкой пагинации."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    
    blocks = []
    has_more = True
    start_cursor = None
    
    while has_more:
        params = {"page_size": 100}
        if start_cursor:
            params["start_cursor"] = start_cursor
            
        response = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        blocks.extend(data.get('results', []))
        has_more = data.get('has_more', False)
        start_cursor = data.get('next_cursor')
        
    return blocks


def delete_block(block_id: str):
    """Удаляет блок в Notion."""
    url = f"https://api.notion.com/v1/blocks/{block_id}"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28'}
    resp = requests.delete(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()


def replace_page_content(page_id: str, new_content: str):
    """Заменяет весь контент страницы на новый (для полировки).
    
    1. Удаляет все существующие блоки параллельно с помощью ThreadPoolExecutor
    2. Добавляет новые блоки из new_content
    """
    # 1. Получаем все блоки (с поддержкой пагинации)
    blocks = get_page_blocks(page_id)
    
    if blocks:
        # Параллельное удаление блоков для ускорения процесса (до 12 потоков)
        max_workers = min(len(blocks), 12)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(delete_block, block['id']): block['id'] for block in blocks}
            for future in concurrent.futures.as_completed(futures):
                b_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Ошибка параллельного удаления блока {b_id}: {e}")
    
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


