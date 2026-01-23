# -*- coding: utf-8 -*-
"""Сервис для работы с Pinecone векторной базой."""
import openai
from pinecone import Pinecone

from utils.config import OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_HOST

# Инициализация клиентов
openai.api_key = OPENAI_API_KEY
pc = Pinecone(api_key=PINECONE_API_KEY)
pinecone_index = pc.Index(host=PINECONE_HOST)


def get_text_embedding(text: str):
    """Превращает текст в вектор с помощью OpenAI."""
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
    pinecone_index.upsert(vectors=[(page_id, vector)])
    print(f"Вектор для страницы {page_id} успешно сохранен в Pinecone.")


def query_pinecone(query_text: str, top_k: int = 3):
    """Ищет наиболее похожие векторы в Pinecone."""
    print(f"Создаю вектор для поискового запроса: '{query_text}'")
    query_vector = get_text_embedding(query_text)
    results = pinecone_index.query(
        vector=query_vector,
        top_k=top_k,
        include_values=False
    )
    page_ids = [match['id'] for match in results['matches']]
    print(f"Pinecone нашел ID: {page_ids}")
    return page_ids
