# -*- coding: utf-8 -*-
"""Сервис для работы с Pinecone векторной базой."""

from openai import OpenAI
from pinecone import Pinecone
from utils.config import OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_HOST

# Глобальные клиенты для повторного использования (Warm Start)
_pc = None
_pinecone_index = None
_openai_client = None


def _get_openai_client():
    """Возвращает глобальный переиспользуемый клиент OpenAI."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _get_pinecone_index():
    """Инициализирует и возвращает индекс Pinecone при первом вызове."""
    global _pc, _pinecone_index
    if _pinecone_index is None:
        if not PINECONE_API_KEY or not PINECONE_HOST:
            raise ValueError("PINECONE_API_KEY или PINECONE_HOST не заданы в конфигурации.")
        _pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = _pc.Index(host=PINECONE_HOST)
    return _pinecone_index


def get_text_embedding(text: str):
    """Превращает текст в вектор с помощью OpenAI с переиспользованием клиента."""
    client = _get_openai_client()
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small",
        timeout=2.0
    )
    return response.data[0].embedding


def upsert_to_pinecone(page_id: str, text_content: str):
    """Создает вектор для текста и сохраняет его в Pinecone."""
    if not text_content:
        print(f"Нет контента для индексации страницы {page_id}")
        return
    
    try:
        print(f"Создаю вектор для страницы {page_id}...")
        vector = get_text_embedding(text_content)
        _get_pinecone_index().upsert(vectors=[(page_id, vector)])
        print(f"Вектор для страницы {page_id} успешно сохранен в Pinecone.")
    except Exception as e:
        print(f"ОШИБКА ИНДЕКСАЦИИ В PINECONE: {e}")


def query_pinecone(query_text: str, top_k: int = 3):
    """Ищет наиболее похожие векторы в Pinecone с обработкой ошибок."""
    try:
        print(f"Создаю вектор для поискового запроса: '{query_text}'")
        query_vector = get_text_embedding(query_text)
        results = _get_pinecone_index().query(
            vector=query_vector,
            top_k=top_k,
            include_values=False
        )
        page_ids = [match['id'] for match in results['matches']]
        print(f"Pinecone нашел ID: {page_ids}")
        return page_ids
    except Exception as e:
        print(f"ОШИБКА ПОИСКА В PINECONE: {e}")
        return []


def delete_from_pinecone(page_id: str):
    """Удаляет вектор страницы из Pinecone."""
    try:
        print(f"Удаляю вектор страницы {page_id} из Pinecone...")
        _get_pinecone_index().delete(ids=[page_id])
        print(f"Вектор страницы {page_id} успешно удален из Pinecone.")
    except Exception as e:
        print(f"ОШИБКА УДАЛЕНИЯ ИЗ PINECONE: {e}")


def clear_pinecone_index():
    """Полностью очищает весь индекс Pinecone (удаляет все векторы)."""
    try:
        print("Очищаю весь индекс Pinecone...")
        _get_pinecone_index().delete(delete_all=True)
        print("Индекс Pinecone успешно полностью очищен.")
        return True
    except Exception as e:
        print(f"ОШИБКА ПОЛНОЙ ОЧИСТКИ PINECONE: {e}")
        return False

