# -*- coding: utf-8 -*-
"""Test script for state.py module.

Verifies all functions in state.py and prints detailed results.
Supports both mock in-memory operations and real Upstash Redis REST calls.
"""
import sys
import os

# Setup sys.path to resolve api/ services correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
api_dir = os.path.join(project_root, 'api')

if project_root not in sys.path:
    sys.path.append(project_root)
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from services.state import (
    get_user_state,
    set_user_state,
    get_active_mode,
    set_active_mode,
    get_transcript_clean,
    set_transcript_clean,
    get_transcript_single_mode,
    set_transcript_single_mode,
    get_hidden_tasks,
    add_hidden_task,
    clear_hidden_tasks,
    get_user_settings,
    set_user_settings,
    get_user_xp,
    set_user_xp,
    add_user_xp,
    save_temp_transcript,
    get_temp_transcript,
    get_transcript_buffer,
    append_to_transcript_buffer,
    clear_transcript_buffer,
    log_last_action,
    get_and_delete_last_log,
    get_last_created_page_id,
    redis_client
)


def run_tests():
    print("=" * 60)
    print("🚀 НАЧАЛО ТЕСТИРОВАНИЯ МОДУЛЯ STATE.PY")
    print(f"Используемый бэкенд Redis: {type(redis_client).__name__}")
    print("=" * 60)

    user_id = "test_user_12345"

    # --- 1. ТЕСТ: Настройки пользователя и кэш ---
    print("\n📝 1. Настройки пользователя и кэш:")
    settings = get_user_settings(user_id)
    print(f"   [OK] Дефолтные настройки получены: {settings}")
    
    # Изменяем настройки через словарь
    set_user_settings(user_id, {'reminder_minutes': 30, 'custom_prop': 'hello'})
    updated = get_user_settings(user_id)
    assert updated['reminder_minutes'] == 30, "Ошибка обновления reminder_minutes через dict"
    assert updated.get('custom_prop') == 'hello', "Ошибка сохранения произвольных настроек"
    print("   [OK] Изменение настроек через dict проверено.")

    # Изменяем настройки через int (совместимость с bot.py)
    set_user_settings(user_id, 45)
    updated2 = get_user_settings(user_id)
    assert updated2['reminder_minutes'] == 45, "Ошибка обновления reminder_minutes через int"
    print("   [OK] Изменение настроек через int проверено.")

    # --- 2. ТЕСТ: Состояния (States) ---
    print("\n🔄 2. Управление состояниями (State):")
    # Должно быть None изначально
    assert get_user_state(user_id) is None, "Начальное состояние должно быть None"
    
    # Задаем состояние
    set_user_state(user_id, "awaiting_note_text", "page_abc_123", "Some pending edit text")
    print("   [OK] Состояние успешно сохранено.")
    
    # Читаем состояние (оно должно удалиться после чтения!)
    state_details = get_user_state(user_id)
    assert state_details is not None, "Состояние должно существовать"
    assert state_details['state'] == "awaiting_note_text", "Ошибка значения state"
    assert state_details['page_id'] == "page_abc_123", "Ошибка значения page_id"
    assert state_details['pending_edit_text'] == "Some pending edit text", "Ошибка значения pending_edit_text"
    print(f"   [OK] Состояние успешно считано: {state_details}")

    # Повторный запрос должен вернуть None (одноразовое состояние)
    assert get_user_state(user_id) is None, "Состояние должно удаляться после чтения"
    print("   [OK] Удаление состояния после чтения проверено.")

    # --- 3. ТЕСТ: Активный режим ---
    print("\n⚡️ 3. Активный режим (Active Mode):")
    assert get_active_mode(user_id) == "note", "Дефолтный активный режим должен быть 'note'"
    
    set_active_mode(user_id, "transcript")
    assert get_active_mode(user_id) == "transcript", "Режим не обновился"
    print("   [OK] Запись и чтение активного режима проверены.")
    
    set_active_mode(user_id, None)
    assert get_active_mode(user_id) == "note", "Сброс режима не сработал"
    print("   [OK] Сброс активного режима в None проверен.")

    # --- 4. ТЕСТ: Настройки транскрипта ---
    print("\n🎙 4. Настройки транскрипта (Clean / Single):")
    assert get_transcript_clean(user_id) is False, "Дефолтный transcript_clean должен быть False"
    set_transcript_clean(user_id, True)
    assert get_transcript_clean(user_id) is True, "transcript_clean не обновился"
    print("   [OK] transcript_clean проверен.")

    assert get_transcript_single_mode(user_id) is False, "Дефолтный transcript_single_mode должен быть False"
    set_transcript_single_mode(user_id, True)
    assert get_transcript_single_mode(user_id) is True, "transcript_single_mode не обновился"
    print("   [OK] transcript_single_mode проверен.")

    # --- 5. ТЕСТ: Скрытые задачи ClickUp ---
    print("\n👁 5. Скрытые задачи ClickUp:")
    assert get_hidden_tasks(user_id) == [], "Список скрытых задач должен быть пуст"
    add_hidden_task(user_id, "task_1")
    add_hidden_task(user_id, "task_2")
    add_hidden_task(user_id, "task_1")  # Дубликат
    hidden = get_hidden_tasks(user_id)
    assert len(hidden) == 2, f"Ожидалось 2 уникальные скрытые задачи, получено: {hidden}"
    assert "task_1" in hidden and "task_2" in hidden, "Неверный состав скрытых задач"
    print(f"   [OK] Добавление скрытых задач проверено: {hidden}")
    
    clear_hidden_tasks(user_id)
    assert get_hidden_tasks(user_id) == [], "Список скрытых задач не очистился"
    print("   [OK] Очистка скрытых задач проверена.")

    # --- 6. ТЕСТ: RPG XP Система ---
    print("\n⚔️ 6. RPG XP Система:")
    # Проверка получения XP (совместимость)
    xp_data = get_user_xp(user_id)
    assert xp_data.get('xp') == 0, "Дефолтный XP должен быть 0"
    assert xp_data.get('level') == 1, "Дефолтный Level должен быть 1"
    
    # Проверка поведения XPDataDict как int (по ТЗ)
    assert int(xp_data) == 0, "XPDataDict не приводится к int 0"
    
    # Установка XP в виде dict (clickup_webhook.py совместимость)
    set_user_xp(user_id, {'xp': 120, 'level': 2})
    xp_data2 = get_user_xp(user_id)
    assert xp_data2.get('xp') == 120, "Ошибка установки XP через dict"
    assert xp_data2.get('level') == 2, "Ошибка установки Level через dict"
    assert int(xp_data2) == 120, "XPDataDict не приводится к int 120"
    print("   [OK] Установка XP через dict и приведение к int проверено.")

    # Увеличение XP
    add_user_xp(user_id, 30)
    xp_data3 = get_user_xp(user_id)
    assert xp_data3.get('xp') == 150, f"Ошибка инкремента XP, ожидалось 150, получено: {xp_data3.get('xp')}"
    print(f"   [OK] Инкремент XP проверен: {xp_data3}")

    # --- 7. ТЕСТ: Временные транскрипты ---
    print("\n💾 7. Временные транскрипты:")
    text = "Длинный текст транскрипта, сохраненный для callback кнопок Telegram."
    log_id = save_temp_transcript(user_id, text)
    assert log_id is not None, "log_id временного транскрипта не должен быть None"
    print(f"   [OK] Временный транскрипт сохранен с ID: {log_id}")
    
    retrieved = get_temp_transcript(log_id)
    assert retrieved == text, "Полученный текст не совпадает с сохраненным"
    print("   [OK] Временный транскрипт успешно прочитан.")
    
    # Должен удаляться после первого чтения
    assert get_temp_transcript(log_id) is None, "Временный транскрипт должен удаляться после чтения"
    print("   [OK] Удаление временного транскрипта после чтения проверено.")

    # --- 8. ТЕСТ: Буфер мульти-транскрипта ---
    print("\n🎙💬 8. Буфер мульти-транскрипта:")
    # Изначально буфер пуст
    buf_id, buf_content = get_transcript_buffer(user_id)
    assert buf_content == "", f"Буфер должен быть пуст, получено: {buf_content}"
    
    # Добавляем части
    append_to_transcript_buffer(user_id, "Часть 1")
    append_to_transcript_buffer(user_id, "Часть 2")
    buf_id, content = get_transcript_buffer(user_id)
    expected_content = "Часть 1\n\n---\n\nЧасть 2"
    assert content == expected_content, f"Неверное содержимое буфера: '{content}'"
    print(f"   [OK] Содержимое буфера мульти-транскрипта проверено: '{content}'")
    
    clear_transcript_buffer(user_id)
    _, final_content = get_transcript_buffer(user_id)
    assert final_content == "", "Буфер мульти-транскрипта не очистился"
    print("   [OK] Очистка буфера мульти-транскрипта проверена.")

    # --- 9. ТЕСТ: Логирование последних действий (Undo) ---
    print("\n🔙 9. Логирование действий (Undo):")
    # Логируем Notion заметку
    log_last_action(user_id, action="create_note", page_id="notion_page_999")
    # Логируем Google Calendar событие
    log_last_action(user_id, action="create_event", gcal_event_id="gcal_event_777")
    
    # Проверка получения ID последней страницы Notion
    last_page = get_last_created_page_id(user_id)
    assert last_page == "notion_page_999", f"Неверный ID последней страницы: {last_page}"
    print(f"   [OK] ID последней созданной страницы Notion найден в логах: {last_page}")

    # Отмена (LPOP) - последнее действие было с gcal_event_777
    action1 = get_and_delete_last_log(user_id)
    assert action1['gcal_event_id'] == "gcal_event_777", "Неверное первое действие для отмены"
    
    # Предпоследнее действие - с notion_page_999
    action2 = get_and_delete_last_log(user_id)
    assert action2['notion_page_id'] == "notion_page_999", "Неверное второе действие для отмены"
    
    assert get_and_delete_last_log(user_id) is None, "Лог действий должен быть пуст"
    print("   [OK] Логирование, отмена действий и поиск последней страницы проверены.")

    print("\n" + "=" * 60)
    print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
