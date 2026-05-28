# -*- coding: utf-8 -*-
"""Сервис для работы с Pinecone векторной базой."""

from utils.config import OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_HOST

# Лази-инициализация клиентов
_pc = None
_pinecone_index = None

def _get_pinecone_index():
    """Инициализирует и возвращает индекс Pinecone при первом вызове."""
    global _pc, _pinecone_index
    if _pinecone_index is None:
        if not PINECONE_API_KEY or not PINECONE_HOST:
            raise ValueError("PINECONE_API_KEY или PINECONE_HOST не заданы в конфигурации.")
        from pinecone import Pinecone
        _pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = _pc.Index(host=PINECONE_HOST)
    return _pinecone_index


def get_text_embedding(text: str):
    """Превращает текст в вектор с помощью OpenAI."""
    import openai
    openai.api_key = OPENAI_API_KEY
    response = openai.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding


def upsert_to_pinecone(page_id: str, text_content: str):
    """Создает вектор для текста и сохраняет его в Pinecone."""
    if not text_content:
        print(f"Нет контента для индексации страницы {page_id}")
        return
    
    print(f"Создаю вектор для страницы {page_id}...")
    vector = get_text_embedding(text_content)
    _get_pinecone_index().upsert(vectors=[(page_id, vector)])
    print(f"Вектор для страницы {page_id} успешно сохранен в Pinecone.")


def query_pinecone(query_text: str, top_k: int = 3):
    """Ищет наиболее похожие векторы в Pinecone."""
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
