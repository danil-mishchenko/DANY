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


def add_to_notion_page(page_id: str, text_to_add: str):
    """Добавляет новые блоки текста в конец страницы Notion."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    new_blocks = parse_to_notion_blocks(text_to_add)
    payload = {'children': new_blocks}
    requests.patch(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT).raise_for_status()


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
        'page_id': get_text(properties.get('NotionPageID'))
    }
    
    delete_notion_page(state_page_id)
    return state_details
