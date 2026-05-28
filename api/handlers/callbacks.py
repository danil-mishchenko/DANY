# -*- coding: utf-8 -*-
"""Callback Query Handler for Telegram Bot."""

import re
from services.telegram import (
    send_telegram_message,
    edit_telegram_message,
    answer_callback_query
)
from services.notion import (
    get_latest_notes,
    get_notion_page_content,
    create_notion_page,
    delete_notion_page,
    add_to_notion_page,
    get_page_title,
    get_page_preview,
    replace_page_content,
    restore_notion_page
)
from services.state import (
    get_and_delete_last_log,
    set_user_state,
    get_user_state,
    get_transcript_clean,
    set_transcript_clean,
    get_transcript_single_mode,
    set_transcript_single_mode,
    save_temp_transcript,
    get_temp_transcript,
    get_transcript_buffer,
    clear_transcript_buffer,
    set_active_mode,
    get_hidden_tasks,
    set_hidden_tasks,
    add_hidden_task,
    set_user_settings
)
from services.calendar import delete_gcal_event
from services.clickup import get_my_tasks, format_tasks_message
from services.ai import (
    process_with_ai,
    polish_content,
    summarize_transcript
)
from utils.ui import build_settings_message

def handle_callback(chat_id: int, user_id: str, callback_query_id: str, callback_data: str, callback_query: dict):
    """Обработка inline кнопок."""
    if callback_data == 'undo_last_action':
        answer_callback_query(callback_query_id)
        last_action = get_and_delete_last_log()
        if last_action:
            if last_action.get('notion_page_id'): 
                delete_notion_page(last_action['notion_page_id'])
            if last_action.get('gcal_event_id') and last_action.get('gcal_calendar_id'): 
                delete_gcal_event(last_action['gcal_calendar_id'], last_action['gcal_event_id'])
            send_telegram_message(chat_id, "✅ Последнее действие отменено.")
        else:
            send_telegram_message(chat_id, "🤔 Не найдено действий для отмены.")
    
    elif callback_data.startswith('delete_notion_'):
        answer_callback_query(callback_query_id)
        page_id_to_delete = callback_data.split('_', 2)[2]
        message_id = callback_query['message']['message_id']
        try:
            # Получаем название перед удалением
            page_title = get_page_title(page_id_to_delete)
            delete_notion_page(page_id_to_delete)
            # Редактируем сообщение вместо отправки нового
            buttons = [
                [
                    {"text": "♻️ Восстановить", "callback_data": f"restore_{page_id_to_delete}"},
                    {"text": "🔙 К списку", "callback_data": "back_to_notes_list"}
                ]
            ]
            edit_telegram_message(
                chat_id, 
                message_id, 
                f"🗑️ ~{page_title}~ удалена",
                inline_buttons=buttons
            )
        except Exception as e:
            edit_telegram_message(chat_id, message_id, f"❌ Ошибка: {e}")
    
    elif callback_data.startswith('restore_'):
        answer_callback_query(callback_query_id)
        page_id_to_restore = callback_data.replace('restore_', '')
        message_id = callback_query['message']['message_id']
        try:
            restore_notion_page(page_id_to_restore)
            page_title = get_page_title(page_id_to_restore)
            preview = get_page_preview(page_id_to_restore, max_chars=60)
            # Восстанавливаем оригинальные кнопки
            buttons = [[
                {"text": "👁️", "callback_data": f"view_page_{page_id_to_restore}"},
                {"text": "➕", "callback_data": f"add_to_notion_{page_id_to_restore}"},
                {"text": "✏️", "callback_data": f"rename_page_{page_id_to_restore}"},
                {"text": "🗑️", "callback_data": f"delete_notion_{page_id_to_restore}"}
            ]]
            note_text = f"📋 *{page_title}*\n_{preview['preview']}_"
            edit_telegram_message(chat_id, message_id, note_text, inline_buttons=buttons)
        except Exception as e:
            edit_telegram_message(chat_id, message_id, f"❌ Ошибка восстановления: {e}")

    elif callback_data.startswith('add_to_notion_'):
        answer_callback_query(callback_query_id)
        page_id = callback_data.split('_', 3)[3]
        set_user_state(str(chat_id), 'awaiting_add_text', page_id)
        send_telegram_message(chat_id, "▶️ Введите текст, который нужно *добавить* в конец заметки:")
    
    elif callback_data == 'back_to_notes_list':
        answer_callback_query(callback_query_id)
        # Возврат к списку заметок
        message_id = callback_query['message']['message_id']
        # Получаем свежий список заметок
        latest_notes = get_latest_notes(5)
        
        if not latest_notes:
             edit_telegram_message(chat_id, message_id, "😔 Заметок пока нет.")
        else:
            message_text = "📋 *Ваши последние заметки:*\n\n"
            navigation_buttons = []
            for i, note in enumerate(latest_notes):
                page_id = note['id']
                title_parts = note.get('properties', {}).get('Name', {}).get('title', [])
                full_title = title_parts[0]['plain_text'] if title_parts else "Без названия"
                button_title = (full_title[:20] + '..') if len(full_title) > 20 else full_title
                
                message_text += f"*{i+1}. {full_title}*\n"
                navigation_buttons.append([{"text": f"{i+1}. {button_title}", "callback_data": f"note_menu_{page_id}"}])
            
            edit_telegram_message(chat_id, message_id, message_text, inline_buttons=navigation_buttons)

    elif callback_data.startswith('note_menu_'):
        answer_callback_query(callback_query_id)
        # Открытие меню конкретной заметки
        page_id = callback_data.replace('note_menu_', '')
        message_id = callback_query['message']['message_id']
        try:
            title = get_page_title(page_id)
            preview = get_page_preview(page_id, max_chars=100)
            
            buttons = [
                [
                    {"text": "👁️ Просмотр", "callback_data": f"view_page_{page_id}"},
                    {"text": "✏️ Переименовать", "callback_data": f"rename_page_{page_id}"},
                ],
                [
                    {"text": "➕ Добавить текст", "callback_data": f"add_to_notion_{page_id}"},
                    {"text": "🗑️ Удалить", "callback_data": f"delete_notion_{page_id}"}
                ],
                [
                    {"text": "🔙 Назад к списку", "callback_data": "back_to_notes_list"}
                ]
            ]
            
            msg = f"📋 *{title}*\n\n_{preview['preview']}_"
            edit_telegram_message(chat_id, message_id, msg, inline_buttons=buttons)
        except Exception as e:
            edit_telegram_message(chat_id, message_id, f"❌ Ошибка загрузки заметки: {e}")

    elif callback_data.startswith('rename_page_'):
        answer_callback_query(callback_query_id)
        page_id = callback_data.replace('rename_page_', '')
        set_user_state(str(chat_id), 'awaiting_rename', page_id)
        send_telegram_message(chat_id, "✏️ Введите новое название заметки:")
    
    elif callback_data.startswith('view_page_'):
        answer_callback_query(callback_query_id)
        page_id = callback_data.replace('view_page_', '')
        message_id = callback_query['message']['message_id']
        try:
            title = get_page_title(page_id)
            content = get_notion_page_content(page_id)
            # Ограничиваем длину для Telegram
            if len(content) > 3000:
                content = content[:3000] + "\n\n... _(текст обрезан)_"
            
            buttons = [[{"text": "🔙 Назад", "callback_data": f"note_menu_{page_id}"}]]
            
            edit_telegram_message(chat_id, message_id, f"📋 *{title}*\n\n{content}", inline_buttons=buttons)
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка при загрузке: {e}")
    
    elif callback_data.startswith('edit_simple_'):
        answer_callback_query(callback_query_id)
        # Просто добавить текст без полировки
        page_id = callback_data.replace('edit_simple_', '')
        user_state = get_user_state(str(chat_id))
        if user_state and user_state.get('pending_edit_text'):
            text_to_add = user_state['pending_edit_text']
            try:
                add_to_notion_page(page_id, text_to_add)
                title = get_page_title(page_id)
                send_telegram_message(chat_id, f"✅ Добавлено в *{title}*", show_keyboard=True)
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Ошибка: {e}")
            set_user_state(str(chat_id), None, None)  # Очищаем state
        else:
            send_telegram_message(chat_id, "❌ Текст для добавления не найден.")
    
    elif callback_data.startswith('edit_polish_'):
        answer_callback_query(callback_query_id)
        # Добавить + полировка через AI
        page_id = callback_data.replace('edit_polish_', '')
        user_state = get_user_state(str(chat_id))
        if user_state and user_state.get('pending_edit_text'):
            new_text = user_state['pending_edit_text']
            try:
                send_telegram_message(chat_id, "✨ Полирую текст...")
                old_content = get_notion_page_content(page_id)
                polished = polish_content(old_content, new_text)
                replace_page_content(page_id, polished)
                title = get_page_title(page_id)
                send_telegram_message(chat_id, f"✅ *{title}* обновлена и отполирована!", show_keyboard=True)
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Ошибка полировки: {e}")
            set_user_state(str(chat_id), None, None)
        else:
            send_telegram_message(chat_id, "❌ Текст для добавления не найден.")
    
    elif callback_data.startswith('set_reminder_'):
        answer_callback_query(callback_query_id)
        # Обработка установки времени напоминания
        minutes = int(callback_data.replace('set_reminder_', ''))
        set_user_settings(str(chat_id), minutes)
        
        if minutes == 0:
            send_telegram_message(chat_id, "🔕 Уведомления в Telegram *отключены*.", show_keyboard=True)
        else:
            send_telegram_message(chat_id, f"✅ Уведомления будут приходить за *{minutes} мин* до события.", show_keyboard=True)
    
    elif callback_data == 'clickup_refresh':
        answer_callback_query(callback_query_id)
        # Обновляем список задач ClickUp
        hidden_ids = get_hidden_tasks(user_id)
        tasks = get_my_tasks()
        msg = format_tasks_message(tasks, hidden_ids=hidden_ids)
        buttons = [[{"text": "🔄 Обновить", "callback_data": "clickup_refresh"}]]
        if hidden_ids:
            buttons.append([{"text": f"👁 Показать скрытые ({len(hidden_ids)})", "callback_data": "unhide_all"}])
        if tasks:
            buttons.append([{"text": "🌐 Открыть ClickUp", "url": "https://app.clickup.com"}])
        edit_telegram_message(chat_id, callback_query['message']['message_id'], msg, inline_buttons=buttons)
    
    elif callback_data.startswith('hide_task_'):
        task_id = callback_data.replace('hide_task_', '')
        add_hidden_task(user_id, task_id)
        answer_callback_query(callback_query['id'], "👁 Задача скрыта")
        # Обновляем меню /hide
        hidden_ids = get_hidden_tasks(user_id)
        tasks = get_my_tasks()
        visible = [t for t in tasks if t.get('id', '') not in hidden_ids]
        
        buttons = []
        for t in visible[:10]:
            short_name = t['name'][:30] + ('...' if len(t['name']) > 30 else '')
            tags = f"[{', '.join(t.get('tags', []))}] " if t.get('tags') else ""
            buttons.append([{"text": f"👁 {tags}{short_name}", "callback_data": f"hide_task_{t['id']}"}])
        if hidden_ids:
            buttons.append([{"text": f"✅ Показать все скрытые ({len(hidden_ids)})", "callback_data": "unhide_all"}])
        
        msg = f"👁 *Скрыть задачи*\n\nНажми на задачу чтобы скрыть.\nСкрыто сейчас: *{len(hidden_ids)}*"
        edit_telegram_message(chat_id, callback_query['message']['message_id'], msg, inline_buttons=buttons)
    
    elif callback_data == 'unhide_all':
        set_hidden_tasks(user_id, [])
        answer_callback_query(callback_query['id'], "✅ Все задачи показаны")
        tasks = get_my_tasks()
        msg = format_tasks_message(tasks)
        buttons = [[{"text": "🔄 Обновить", "callback_data": "clickup_refresh"}]]
        if tasks:
            buttons.append([{"text": "🌐 Открыть ClickUp", "url": "https://app.clickup.com"}])
        edit_telegram_message(chat_id, callback_query['message']['message_id'], msg, inline_buttons=buttons)
    
    elif callback_data == 'exit_transcript':
        answer_callback_query(callback_query_id)
        set_active_mode(user_id, None)
        send_telegram_message(chat_id, "✅ Режим транскрипта выключен.", show_keyboard=True)
    
    elif callback_data in ('set_transcript_clean', 'set_transcript_raw', 'set_transcript_single_mode', 'set_transcript_multi_mode'):
        if callback_data == 'set_transcript_clean':
            set_transcript_clean(user_id, True)
        elif callback_data == 'set_transcript_raw':
            set_transcript_clean(user_id, False)
        elif callback_data == 'set_transcript_single_mode':
            set_transcript_single_mode(user_id, True)
        elif callback_data == 'set_transcript_multi_mode':
            set_transcript_single_mode(user_id, False)
            
        answer_callback_query(callback_query_id, "Настройки обновлены")
        # Обновляем меню настроек
        msg, buttons = build_settings_message(user_id)
        edit_telegram_message(chat_id, callback_query['message']['message_id'], msg, inline_buttons=buttons)
    
    elif callback_data.startswith('save_transcript_'):
        answer_callback_query(callback_query_id)
        log_id = callback_data.replace('save_transcript_', '')
        message_id = callback_query['message']['message_id']
        transcript_text = get_temp_transcript(log_id)
        
        if transcript_text:
            # Сохраняем как новую заметку
            ai_data = process_with_ai(transcript_text)
            title = ai_data.get('main_title', 'Транскрипт')
            category = ai_data.get('category', 'Мысль')
            
            try:
                # Убираем разметки markdown если есть
                clean_text = re.sub(r'[*_`]', '', transcript_text)
                new_page_id = create_notion_page(title, clean_text, category)
                
                buttons = [[
                    {"text": "👁️ Просмотр", "callback_data": f"view_page_{new_page_id}"},
                    {"text": "🗑️ Удалить", "callback_data": f"delete_notion_{new_page_id}"}
                ]]
                edit_telegram_message(chat_id, message_id, f"✅ Транскрипт сохранен как заметка: *{title}*", inline_buttons=buttons)
            except Exception as e:
                print(f"Ошибка сохранения транскрипта: {e}")
                edit_telegram_message(chat_id, message_id, f"❌ Ошибка сохранения заметки.")
        else:
            edit_telegram_message(chat_id, message_id, "❌ Транскрипт устарел или уже сохранен.")
            
    elif callback_data.startswith('summarize_transcript_'):
        answer_callback_query(callback_query_id)
        log_id = callback_data.replace('summarize_transcript_', '')
        message_id = callback_query['message']['message_id']
        
        transcript_text = get_temp_transcript(log_id) # Текст удаляется после этого
        if transcript_text:
            edit_telegram_message(chat_id, message_id, "⏳ Генерирую резюме...")
            try:
                summary = summarize_transcript(transcript_text)
                
                # Пересохраняем оригинал для возможности сохранить в Notion
                new_log_id = save_temp_transcript(user_id, transcript_text)
                
                msg = f"📊 *Выжимка транскрипта:*\n\n{summary}\n\n_Оригинальный текст сохранен во временный буфер._"
                buttons = []
                if new_log_id:
                    buttons.append([{"text": "💾 Сохранить в Notion", "callback_data": f"save_transcript_{new_log_id}"}])
                buttons.append([{"text": "🔙 Закрыть", "callback_data": "exit_transcript"}])
                
                edit_telegram_message(chat_id, message_id, msg, inline_buttons=buttons)
                
            except Exception as e:
                print(f"Ошибка резюме: {e}")
                edit_telegram_message(chat_id, message_id, "❌ Ошибка при генерации резюме.")
        else:
            edit_telegram_message(chat_id, message_id, "❌ Транскрипт устарел и был удален.")
            
    elif callback_data == 'transcript_finish':
        answer_callback_query(callback_query_id)
        # Завершаем мульти-транскрипт
        message_id = callback_query['message']['message_id']
        _, buffer_content = get_transcript_buffer(user_id)
        clear_transcript_buffer(user_id)
        
        if buffer_content:
            # Очищаем сепараторы в начале
            if buffer_content.startswith("\n\n---\n\n"):
                 buffer_content = buffer_content[9:]
                 
            # Сохраняем во временный лог для кнопок
            log_id = save_temp_transcript(user_id, buffer_content)
            buttons = []
            if log_id:
                buttons.append([
                    {"text": "💾 В Notion", "callback_data": f"save_transcript_{log_id}"},
                    {"text": "📊 Резюме", "callback_data": f"summarize_transcript_{log_id}"}
                ])
                
            buttons.append([{"text": "🔙 Выйти из режима", "callback_data": "exit_transcript"}])
            
            max_len = 3900
            if len(buffer_content) <= max_len:
                edit_telegram_message(chat_id, message_id, f"✅ *Мульти-транскрипт завершен:*\n\n{buffer_content}", inline_buttons=buttons)
            else:
                # Ограничиваем превью
                preview = buffer_content[:max_len] + "\n\n... _(Текст обрезан)_"
                edit_telegram_message(chat_id, message_id, f"✅ *Мульти-транскрипт завершен (Слишком длинный):*\n\n{preview}", inline_buttons=buttons)
        else:
            edit_telegram_message(chat_id, message_id, "❌ Нет активного буфера транскриптов.")
 
    elif callback_data == 'transcript_clear':
        answer_callback_query(callback_query_id)
        # Очищаем мульти-транскрипт
        message_id = callback_query['message']['message_id']
        clear_transcript_buffer(user_id)
        edit_telegram_message(chat_id, message_id, "🗑️ Буфер мульти-транскрипта очищен.")
