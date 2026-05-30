# -*- coding: utf-8 -*-
"""Скрипт для комплексного локального тестирования поисковых инноваций DANY."""
import os
import sys
from datetime import datetime, timezone, timedelta

# Добавляем путь к api в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../api')))

from services.state import (
    set_note_content_cache,
    get_note_content_cache,
    delete_note_content_cache,
    set_note_metadata,
    get_note_metadata,
    delete_note_metadata
)
from services.pinecone_svc import (
    split_content_into_smart_chunks,
    apply_temporal_decay
)
from services.ai import expand_search_query
from services.calendar import get_calendar_events_for_range


def run_tests():
    print("🧪 НАЧАЛО ТЕСТИРОВАНИЯ ПОИСКОВЫХ ИННОВАЦИЙ DANY...\n")
    
    # -------------------------------------------------------------
    # ТЕСТ 1: Перманентный Redis кэш контента
    # -------------------------------------------------------------
    print("=== ТЕСТ 1: Перманентный Redis-кэш контента ===")
    test_page_id = "test-page-uuid-12345"
    test_content = "# Тестовая заметка\n\n- [ ] Купить хлеб\n- [ ] Купить молоко\n\nЭто важная заметка."
    
    print(f"Записываю тестовый контент для {test_page_id}...")
    set_note_content_cache(test_page_id, test_content)
    
    cached = get_note_content_cache(test_page_id)
    if cached == test_content:
        print("✅ Кэширование контента работает идеально!")
    else:
        print(f"❌ Ошибка кэширования! Получено: {cached}")
        
    # -------------------------------------------------------------
    # ТЕСТ 2: Перманентный кэш метаданных
    # -------------------------------------------------------------
    print("\n=== ТЕСТ 2: Кэш метаданных заметок ===")
    test_meta = {
        'title': 'Тестовая заметка',
        'category': 'Покупка',
        'created_time': '2026-05-30T12:00:00+03:00',
        'last_edited_time': '2026-05-30T18:00:00+03:00'
    }
    
    print(f"Записываю метаданные для {test_page_id}...")
    set_note_metadata(test_page_id, test_meta)
    
    cached_meta = get_note_metadata(test_page_id)
    if cached_meta and cached_meta['category'] == 'Покупка' and cached_meta['title'] == 'Тестовая заметка':
        print("✅ Кэширование метаданных работает идеально!")
    else:
        print(f"❌ Ошибка метаданных! Получено: {cached_meta}")
        
    # Очищаем
    delete_note_content_cache(test_page_id)
    delete_note_metadata(test_page_id)
    
    # -------------------------------------------------------------
    # ТЕСТ 3: Умный чанкер списков и абзацев (Parent-Child)
    # -------------------------------------------------------------
    print("\n=== ТЕСТ 3: Умный чанкер списков и абзацев ===")
    complex_text = (
        "# Заголовок заметки\n\n"
        "Это обычный абзац текста, который должен векторизоваться отдельно.\n\n"
        "### Список продуктов\n"
        "- [ ] Картофель\n"
        "- [ ] Морковь\n"
        "- [ ] Лук репчатый\n\n"
        "И еще один отдельный абзац в самом конце."
    )
    
    chunks = split_content_into_smart_chunks(complex_text)
    print(f"Текст нарезан на {len(chunks)} чанков:")
    for idx, chunk in enumerate(chunks):
        print(f"  --- Чанк {idx + 1} ---")
        print(chunk)
        
    # Проверяем, что список продуктов остался цельным
    list_chunk_found = False
    for chunk in chunks:
        if "Морковь" in chunk and "Картофель" in chunk:
            list_chunk_found = True
            
    if len(chunks) == 4 and list_chunk_found:
        print("✅ Умный чанкер успешно сгруппировал списки продуктов и разбил абзацы!")
    else:
        print(f"❌ Ошибка нарезки чанкера! Всего чанков: {len(chunks)}")
        
    # -------------------------------------------------------------
    # ТЕСТ 4: Временное затухание релевантности (Recency-Bias)
    # -------------------------------------------------------------
    print("\n=== ТЕСТ 4: Временное затухание релевантности (Recency-Bias) ===")
    matches = [
        {'id': 'fresh-note-1', 'score': 0.8},
        {'id': 'old-note-2', 'score': 0.9} # Изначально скор выше, но она старая!
    ]
    
    now = datetime.now(timezone.utc)
    note_meta_dates = {
        'fresh-note-1': now - timedelta(days=2),  # 2 дня назад
        'old-note-2': now - timedelta(days=120)    # 120 дней назад
    }
    
    decayed_matches = apply_temporal_decay(matches, note_meta_dates)
    print("Результаты после применения временного затухания:")
    for m in decayed_matches:
        print(f"  ID: {m['id']} | Итоговый Score: {m['score']:.4f}")
        
    if decayed_matches[0]['id'] == 'fresh-note-1':
        print("✅ Свежая заметка успешно поднялась выше старой за счет временного затухания!")
    else:
        print("❌ Ошибка затухания релевантности!")
        
    # -------------------------------------------------------------
    # ТЕСТ 5: ИИ-расширение запросов (Multi-Query Expansion)
    # -------------------------------------------------------------
    print("\n=== ТЕСТ 5: ИИ-расширение запросов ===")
    test_query = "поездка в будапешт на выходные"
    print(f"Запрос пользователя: '{test_query}'")
    
    if not os.environ.get('OPENAI_API_KEY'):
        print("⚠️ Пропускаю сетевой тест OpenAI (нет OPENAI_API_KEY в .env)")
    else:
        expanded = expand_search_query(test_query)
        print(f"Расширенные синонимы ИИ: {expanded}")
        if len(expanded) > 1 and expanded[0] == test_query:
            print("✅ ИИ-расширение поисковых запросов работает отлично!")
        else:
            print("❌ Ошибка расширения поискового запроса!")
            
    # -------------------------------------------------------------
    # ТЕСТ 6: Чтение событий Google Календаря
    # -------------------------------------------------------------
    print("\n=== ТЕСТ 6: Чтение событий Google Календаря ===")
    if not os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        print("⚠️ Пропускаю сетевой тест Google Calendar (нет GOOGLE_CREDENTIALS_JSON в .env)")
    else:
        try:
            start_iso = datetime.now(timezone.utc).isoformat()
            end_iso = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
            events = get_calendar_events_for_range(start_iso, end_iso)
            print(f"Получено {len(events)} событий из календаря.")
            print("✅ Интеграция Google Calendar API работает успешно!")
        except Exception as e:
            print(f"❌ Ошибка теста календаря: {e}")

    print("\n🎉 ТЕСТИРОВАНИЕ ЗАВЕРШЕНО.")


if __name__ == '__main__':
    run_tests()
