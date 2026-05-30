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


# === NEW INNOVATIONS: PARENT-CHILD CHUNKING & TEMPORAL DECAY ===

def split_content_into_smart_chunks(text: str) -> list:
    """Разбивает текст на смысловые абзацы, удерживая списки покупок и To-Do вместе."""
    lines = text.split("\n")
    chunks = []
    current_chunk = []
    in_list = False
    
    for line in lines:
        stripped = line.strip()
        # Проверяем, является ли строка элементом списка
        is_list_item = stripped.startswith(("- [ ]", "- [x]", "-", "*"))
        
        if is_list_item:
            in_list = True
            current_chunk.append(line)
        else:
            if in_list:
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = []
                in_list = False
            
            if stripped == "":
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = []
            else:
                current_chunk.append(line)
                
    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    return [c.strip() for c in chunks if c.strip()]


def delete_from_pinecone_by_prefix(page_id: str):
    """Удаляет все векторы чанков для заданной страницы из Pinecone."""
    try:
        page_id = str(page_id)
        # В Pinecone удаление по префиксу или ID чанков. 
        # Поскольку у нас нет namespaces в бесплатном тарифе, 
        # мы удаляем поштучно, генерируя ID чанков от 0 до 50
        chunk_ids = [f"{page_id}#chunk_{i}" for i in range(50)]
        # Также пробуем удалить и сам оригинальный page_id на случай, если он был проиндексирован целиком
        chunk_ids.append(page_id)
        
        print(f"Удаляю чанки страницы {page_id} из Pinecone...")
        _get_pinecone_index().delete(ids=chunk_ids)
        print(f"Чанки страницы {page_id} удалены.")
    except Exception as e:
        print(f"ОШИБКА УДАЛЕНИЯ ЧАНКОВ ИЗ PINECONE: {e}")


def upsert_parent_child_chunks(page_id: str, title: str, text_content: str):
    """Дробит текст заметки на смысловые чанки, генерирует векторы и заливает в Pinecone."""
    if not text_content:
        return
        
    try:
        # 1. Сначала очищаем старые чанки этой страницы
        delete_from_pinecone_by_prefix(page_id)
        
        # 2. Разбиваем на умные чанки
        chunks = split_content_into_smart_chunks(text_content)
        if not chunks:
            # Если чанков нет, индексируем хотя бы заголовок
            chunks = [f"Заголовок: {title}"]
            
        vectors_to_upsert = []
        for i, chunk in enumerate(chunks[:50]): # Ограничиваем максимум 50 чанками на заметку
            chunk_id = f"{page_id}#chunk_{i}"
            # Добавляем заголовок в начало каждого чанка для сохранения мета-контекста!
            chunk_text = f"Заголовок: {title}\nКонтент: {chunk}"
            vector = get_text_embedding(chunk_text)
            vectors_to_upsert.append((chunk_id, vector))
            
        # 3. Загружаем чанки в Pinecone
        if vectors_to_upsert:
            _get_pinecone_index().upsert(vectors=vectors_to_upsert)
            print(f"Успешно загружено {len(vectors_to_upsert)} чанков для страницы {page_id} в Pinecone.")
    except Exception as e:
        print(f"ОШИБКА ИЕРАРХИЧЕСКОЙ ИНДЕКСАЦИИ В PINECONE для {page_id}: {e}")


def query_pinecone_parent_child(query_text: str, top_k: int = 15) -> list:
    """Ищет чанки в Pinecone, возвращает уникальные ID родителей с их максимальными скорами.
    
    Returns:
        list: список словарей [{'id': page_id, 'score': match_score}]
    """
    try:
        query_vector = get_text_embedding(query_text)
        # Запрашиваем больше результатов из Pinecone (например, top_k * 3), 
        # так как несколько чанков могут принадлежать одной странице
        results = _get_pinecone_index().query(
            vector=query_vector,
            top_k=min(top_k * 3, 100),
            include_values=False
        )
        
        parent_matches = {}
        for match in results.get('matches', []):
            chunk_id = match['id']
            score = match['score']
            
            # Извлекаем оригинальный page_id (отсекаем суффикс #chunk_i)
            parent_id = chunk_id.split("#chunk_")[0]
            
            # Если страница встречается несколько раз, сохраняем МАКСИМАЛЬНЫЙ скор среди чанков
            if parent_id not in parent_matches:
                parent_matches[parent_id] = score
            else:
                parent_matches[parent_id] = max(parent_matches[parent_id], score)
                
        # Формируем список словарей и сортируем по скору
        matches = [{'id': pid, 'score': scr} for pid, scr in parent_matches.items()]
        matches = sorted(matches, key=lambda x: x['score'], reverse=True)
        
        print(f"Parent-Child поиск нашел уникальных родителей: {[m['id'] for m in matches[:top_k]]}")
        return matches[:top_k]
    except Exception as e:
        print(f"ОШИБКА PARENT-CHILD ПОИСКА В PINECONE: {e}")
        return []


def apply_temporal_decay(matches: list, note_meta_dates: dict) -> list:
    """Применяет формулу экспоненциального затухания к скорам результатов.
    
    matches: список словарей [{'id': page_id, 'score': score}]
    note_meta_dates: словарь {page_id: last_edited_datetime}
    """
    import math
    from datetime import datetime, timezone
    
    decayed_matches = []
    now = datetime.now(timezone.utc)
    
    for match in matches:
        page_id = match['id']
        base_score = match['score']
        
        # Получаем дату изменения заметки. Если нет — используем текущее время (без пенальти)
        last_edited = note_meta_dates.get(page_id)
        if not last_edited:
            last_edited = now
            
        # Приводим к timezone.utc если дата naive
        if last_edited.tzinfo is None:
            last_edited = last_edited.replace(tzinfo=timezone.utc)
            
        days_passed = max(0, (now - last_edited).days)
        
        # Экспоненциальное затухание (0.5% в день)
        decay = math.exp(-0.005 * days_passed)
        
        # Ограничиваем максимальный штраф до 0.5, чтобы старые точные совпадения не терялись
        decay = max(0.5, decay)
        
        new_score = base_score * decay
        decayed_matches.append({'id': page_id, 'score': new_score})
        
    # Пересортировываем результаты по новому скору
    return sorted(decayed_matches, key=lambda x: x['score'], reverse=True)


