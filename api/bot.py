# -*- coding: utf-8 -*-
"""Telegram Bot Handler - Main entry point for Vercel serverless function."""
import json
import traceback
import sys
import os
from http.server import BaseHTTPRequestHandler

# --- VERCEL PATH FIX ---
# Добавляем папку 'api' в sys.path, чтобы imports работали правильно
# Vercel запускает из корня (/var/task), а модули лежат в /var/task/api
current_dir = os.getcwd()
api_dir = os.path.join(current_dir, 'api')
if api_dir not in sys.path:
    sys.path.append(api_dir)

# --- Imports (Global Scope) ---
try:
    import requests
    # --- Utils ---
    from utils.config import (
        validate_env_vars,
        TELEGRAM_TOKEN,
        ALLOWED_TELEGRAM_ID,
        DEFAULT_TIMEOUT
    )
    # --- Services ---
    from services.telegram import (
        download_telegram_file,
        get_telegram_file_url,
        send_telegram_message,
        send_initial_status_message,
        edit_telegram_message,
        send_message_with_buttons,
        answer_callback_query
    )
    from services.notion import (
        get_latest_notes,
        get_notion_page_content,
        create_notion_page,
        delete_notion_page,
        add_to_notion_page,
        add_image_to_page,
        get_and_delete_last_log,
        log_last_action,
        set_user_state,
        get_user_state,
        get_last_created_page_id,
        get_page_title,
        get_page_preview,
        replace_page_content,
        rename_page,
        get_user_settings,
        set_user_settings,
        get_hidden_tasks,
        set_hidden_tasks,
        add_hidden_task,
        get_active_mode,
        set_active_mode,
        get_transcript_clean,
        set_transcript_clean
    )
    from services.calendar import (
        create_google_calendar_event,
        delete_gcal_event
    )
    from services.clickup import get_my_tasks, format_tasks_message
    from services.briefing import build_morning_briefing, build_evening_briefing
    from services.ai import (
        transcribe_with_assemblyai,
        process_with_ai,
        summarize_for_search,
        polish_content,
        clean_transcript
    )
    from services.pinecone_svc import (
        upsert_to_pinecone,
        query_pinecone
    )

    # Validate environment variables at startup
    validate_env_vars()

except Exception as e:
    # Критическая ошибка старта - выводим в лог Vercel
    print(f"[CRITICAL STARTUP ERROR] {e}", file=sys.stderr)
    traceback.print_exc()
 



class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chat_id = None
        try:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            update = json.loads(body.decode('utf-8'))

            message = update.get('message')
            callback_query = update.get('callback_query')

            # --- ОБРАБОТКА НАЖАТИЯ КНОПОК ---
            if callback_query:
                callback_data = callback_query['data']
                chat_id = callback_query['message']['chat']['id']
                user_id = str(callback_query['from']['id'])
                callback_query_id = callback_query['id']
                answer_callback_query(callback_query_id)

                if callback_data == 'undo_last_action':
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
                    page_id_to_restore = callback_data.replace('restore_', '')
                    message_id = callback_query['message']['message_id']
                    try:
                        from services.notion import restore_notion_page
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
                    page_id = callback_data.split('_', 3)[3]
                    set_user_state(str(chat_id), 'awaiting_add_text', page_id)
                    send_telegram_message(chat_id, "▶️ Введите текст, который нужно *добавить* в конец заметки:")
                
                elif callback_data == 'back_to_notes_list':
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
                    page_id = callback_data.replace('rename_page_', '')
                    set_user_state(str(chat_id), 'awaiting_rename', page_id)
                    send_telegram_message(chat_id, "✏️ Введите новое название заметки:")
                
                elif callback_data.startswith('view_page_'):
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
                    # Обработка установки времени напоминания
                    minutes = int(callback_data.replace('set_reminder_', ''))
                    set_user_settings(str(chat_id), minutes)
                    
                    if minutes == 0:
                        send_telegram_message(chat_id, "🔕 Уведомления в Telegram *отключены*.", show_keyboard=True)
                    else:
                        send_telegram_message(chat_id, f"✅ Уведомления будут приходить за *{minutes} мин* до события.", show_keyboard=True)
                
                elif callback_data == 'clickup_refresh':
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
                    set_active_mode(user_id, None)
                    send_telegram_message(chat_id, "✅ Режим транскрипта выключен.", show_keyboard=True)
                
                elif callback_data == 'set_transcript_raw':
                    set_transcript_clean(user_id, False)
                    answer_callback_query(callback_query_id, "📜 Дословный режим")
                    # Обновляем меню настроек
                    settings = get_user_settings(user_id)
                    current_minutes = settings.get('reminder_minutes', 15)
                    is_clean = False
                    buttons = [
                        [
                            {"text": "5 мин" + (" ✓" if current_minutes == 5 else ""), "callback_data": "set_reminder_5"},
                            {"text": "15 мин" + (" ✓" if current_minutes == 15 else ""), "callback_data": "set_reminder_15"},
                            {"text": "30 мин" + (" ✓" if current_minutes == 30 else ""), "callback_data": "set_reminder_30"}
                        ],
                        [
                            {"text": "1 час" + (" ✓" if current_minutes == 60 else ""), "callback_data": "set_reminder_60"},
                            {"text": "Выкл" + (" ✓" if current_minutes == 0 else ""), "callback_data": "set_reminder_0"}
                        ],
                        [
                            {"text": "📜 Дословный ✓", "callback_data": "set_transcript_raw"},
                            {"text": "✨ Чистый", "callback_data": "set_transcript_clean"}
                        ]
                    ]
                    msg = f"⚙️ *Настройки*\n\n📱 *Уведомления*\nЗа сколько минут до события?\n_Текущее: {current_minutes} мин_\n\n🎙 *Транскрипт*\nПодрежим расшифровки:\n_📜 Дословный — точная цитата_"
                    edit_telegram_message(chat_id, callback_query['message']['message_id'], msg, inline_buttons=buttons)
                
                elif callback_data == 'set_transcript_clean':
                    set_transcript_clean(user_id, True)
                    answer_callback_query(callback_query_id, "✨ Чистый режим")
                    # Обновляем меню настроек
                    settings = get_user_settings(user_id)
                    current_minutes = settings.get('reminder_minutes', 15)
                    is_clean = True
                    buttons = [
                        [
                            {"text": "5 мин" + (" ✓" if current_minutes == 5 else ""), "callback_data": "set_reminder_5"},
                            {"text": "15 мин" + (" ✓" if current_minutes == 15 else ""), "callback_data": "set_reminder_15"},
                            {"text": "30 мин" + (" ✓" if current_minutes == 30 else ""), "callback_data": "set_reminder_30"}
                        ],
                        [
                            {"text": "1 час" + (" ✓" if current_minutes == 60 else ""), "callback_data": "set_reminder_60"},
                            {"text": "Выкл" + (" ✓" if current_minutes == 0 else ""), "callback_data": "set_reminder_0"}
                        ],
                        [
                            {"text": "📜 Дословный", "callback_data": "set_transcript_raw"},
                            {"text": "✨ Чистый ✓", "callback_data": "set_transcript_clean"}
                        ]
                    ]
                    msg = f"⚙️ *Настройки*\n\n📱 *Уведомления*\nЗа сколько минут до события?\n_Текущее: {current_minutes} мин_\n\n🎙 *Транскрипт*\nПодрежим расшифровки:\n_✨ Чистый — без слов-заполнителей_"
                    edit_telegram_message(chat_id, callback_query['message']['message_id'], msg, inline_buttons=buttons)
                
                self.send_response(200)
                self.end_headers()
                return

            # --- ОБРАБОТКА СООБЩЕНИЙ ---
            if not message:
                self.send_response(200)
                self.end_headers()
                return

            user_id = str(message['from']['id'])
            chat_id = message['chat']['id']

            allowed_id = ALLOWED_TELEGRAM_ID.strip() if ALLOWED_TELEGRAM_ID else ""
            if user_id != allowed_id:
                self.send_response(200)
                self.end_headers()
                return
            
            # ПРОВЕРКА СОСТОЯНИЯ: не ждем ли мы текст для добавления/переименования/поиска?
            user_state = get_user_state(user_id)
            if user_state:
                state_type = user_state.get('state')
                
                if state_type == 'awaiting_add_text':
                    page_id_to_edit = user_state['page_id']
                    text_to_add = message.get('text', '')
                    if text_to_add:
                        add_to_notion_page(page_id_to_edit, text_to_add)
                        send_telegram_message(chat_id, "✅ Текст успешно добавлен в заметку!", show_keyboard=True)
                    else:
                        send_telegram_message(chat_id, "Отмена. Получено пустое сообщение.")
                    set_user_state(user_id, None, None)  # Очищаем state
                    self.send_response(200)
                    self.end_headers()
                    return
                
                elif state_type == 'awaiting_rename':
                    page_id = user_state['page_id']
                    new_title = message.get('text', '').strip()
                    if new_title:
                        try:
                            rename_page(page_id, new_title)
                            send_telegram_message(chat_id, f"✅ Заметка переименована в *{new_title}*", show_keyboard=True)
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ Ошибка переименования: {e}")
                    else:
                        send_telegram_message(chat_id, "Отмена. Название не может быть пустым.")
                    set_user_state(user_id, None, None)
                    self.send_response(200)
                    self.end_headers()
                    return
                
                elif state_type == 'awaiting_search':
                    query = message.get('text', '').strip()
                    if query:
                        # Переиспользуем логику поиска
                        send_telegram_message(chat_id, f"🧠 Ищу по смыслу: *{query}*...")
                        found_ids = query_pinecone(query, top_k=3)
                        
                        if not found_ids:
                            send_telegram_message(chat_id, "😔 Ничего не найдено.", show_keyboard=True)
                        else:
                            context = ""
                            for page_id in found_ids:
                                try:
                                    page_content = get_notion_page_content(page_id)
                                    page_title = page_content.split('\n', 1)[0] if page_content else "Без названия"
                                    context += f"--- Текст из заметки '{page_title}' ---\n{page_content}\n\n"
                                except Exception as e:
                                    print(f"Не удалось получить контент для страницы {page_id}: {e}")
                            
                            if context:
                                answer = summarize_for_search(context, query)
                                send_telegram_message(chat_id, f"💡 *Вот что я нашел:*\n\n{answer}", show_keyboard=True)
                            else:
                                send_telegram_message(chat_id, "🤔 Нашел заметки, но не смог прочитать.", show_keyboard=True)
                    else:
                        send_telegram_message(chat_id, "Отмена. Пустой запрос.")
                    set_user_state(user_id, None, None)
                    self.send_response(200)
                    self.end_headers()
                    return
            
            text = message.get('text', '')
            
            # АВТОВЫХОД из режима транскрипта при нажатии ДРУГОЙ кнопки клавиатуры
            keyboard_buttons = {"📝 Заметки", "🔍 Поиск", "📋 ClickUp", "⚙️ Настройки"}
            if text in keyboard_buttons:
                active_mode = get_active_mode(user_id)
                if active_mode == 'transcript':
                    set_active_mode(user_id, None)
            
            # ОБРАБОТКА КНОПОК КЛАВИАТУРЫ
            if text == "📝 Заметки":
                text = "/notes"  # Перенаправляем на существующую логику
            elif text == "🔍 Поиск":
                set_user_state(user_id, 'awaiting_search', None)
                send_telegram_message(chat_id, "🔍 Введите поисковый запрос:")
                self.send_response(200)
                self.end_headers()
                return
            elif text == "📋 ClickUp":
                # Показываем задачи из ClickUp
                hidden_ids = get_hidden_tasks(user_id)
                print(f"CLICKUP BUTTON: user_id={user_id}, hidden_ids={hidden_ids}")
                tasks = get_my_tasks()
                print(f"CLICKUP BUTTON: total tasks={len(tasks)}, task_ids={[t.get('id') for t in tasks[:5]]}")
                msg = format_tasks_message(tasks, hidden_ids=hidden_ids)
                
                # Компактные кнопки
                buttons = [[{"text": "🔄 Обновить", "callback_data": "clickup_refresh"}]]
                if hidden_ids:
                    buttons.append([{"text": f"👁 Показать скрытые ({len(hidden_ids)})", "callback_data": "unhide_all"}])
                buttons.append([{"text": "🌐 Открыть ClickUp", "url": "https://app.clickup.com"}])
                
                send_message_with_buttons(chat_id, msg, buttons)
                self.send_response(200)
                self.end_headers()
                return
            elif text == "🎙 Транскрипт":
                # Включаем режим транскрипта
                set_active_mode(user_id, 'transcript')
                is_clean = get_transcript_clean(user_id)
                mode_label = "✨ Чистый" if is_clean else "📜 Дословный"
                buttons = [[{"text": "🔙 Выйти из режима", "callback_data": "exit_transcript"}]]
                send_message_with_buttons(
                    chat_id,
                    f"🎙 *Режим транскрипта активен*\n\n"
                    f"Пересылайте голосовые — получите чистый текст.\n\n"
                    f"Текущий подрежим: {mode_label}\n"
                    f"_Изменить подрежим можно в ⚙️ Настройки_",
                    buttons
                )
                self.send_response(200)
                self.end_headers()
                return
            elif text == "⚙️ Настройки":
                # Показываем меню настроек (расширенное)
                # При входе в настройки — выходим из транскрипт-режима не нужно,
                # настройки работают параллельно
                settings = get_user_settings(user_id)
                current_minutes = settings.get('reminder_minutes', 15)
                is_clean = get_transcript_clean(user_id)
                
                buttons = [
                    [
                        {"text": "5 мин" + (" ✓" if current_minutes == 5 else ""), "callback_data": "set_reminder_5"},
                        {"text": "15 мин" + (" ✓" if current_minutes == 15 else ""), "callback_data": "set_reminder_15"},
                        {"text": "30 мин" + (" ✓" if current_minutes == 30 else ""), "callback_data": "set_reminder_30"}
                    ],
                    [
                        {"text": "1 час" + (" ✓" if current_minutes == 60 else ""), "callback_data": "set_reminder_60"},
                        {"text": "Выкл" + (" ✓" if current_minutes == 0 else ""), "callback_data": "set_reminder_0"}
                    ],
                    [
                        {"text": "📜 Дословный" + (" ✓" if not is_clean else ""), "callback_data": "set_transcript_raw"},
                        {"text": "✨ Чистый" + (" ✓" if is_clean else ""), "callback_data": "set_transcript_clean"}
                    ]
                ]
                
                clean_desc = "✨ Чистый — без слов-заполнителей" if is_clean else "📜 Дословный — точная цитата"
                msg = f"⚙️ *Настройки*\n\n📱 *Уведомления*\nЗа сколько минут до события?\n_Текущее: {current_minutes} мин_\n\n🎙 *Транскрипт*\nПодрежим расшифровки:\n_{clean_desc}_"
                send_message_with_buttons(chat_id, msg, buttons)
                self.send_response(200)
                self.end_headers()
                return

            if text == '/index_all':
                send_telegram_message(chat_id, "Начинаю полную индексацию всех заметок. Это может занять время...")
                all_notes = get_latest_notes(100)
                for note in all_notes:
                    page_id = note['id']
                    page_content = get_notion_page_content(page_id)
                    upsert_to_pinecone(page_id, page_content)
                send_telegram_message(chat_id, f"✅ Готово! Проиндексировано {len(all_notes)} заметок.", show_keyboard=True)
                self.send_response(200)
                self.end_headers()
                return
    
            # ПРОВЕРКА КОМАНД
            if text == '/start':
                send_telegram_message(
                    chat_id, 
                    "👋 *Привет!* Я твой бот для заметок.\n\n"
                    "📝 Просто напиши или запиши голосовое — я создам заметку в Notion.\n\n"
                    "Используй кнопки ниже для навигации:",
                    show_keyboard=True
                )
                self.send_response(200)
                self.end_headers()
                return
            
            elif text == '/briefing':
                send_telegram_message(chat_id, "⏳ Собираю утренний брифинг...")
                try:
                    briefing_msg = build_morning_briefing()
                    send_telegram_message(chat_id, briefing_msg, use_html=True, show_keyboard=True)
                except Exception as e:
                    send_telegram_message(chat_id, f"❌ Ошибка брифинга: {e}", show_keyboard=True)
                self.send_response(200)
                self.end_headers()
                return
            
            elif text == '/evening':
                send_telegram_message(chat_id, "⏳ Собираю вечерний отчёт...")
                try:
                    evening_msg = build_evening_briefing()
                    send_telegram_message(chat_id, evening_msg, use_html=True, show_keyboard=True)
                except Exception as e:
                    send_telegram_message(chat_id, f"❌ Ошибка: {e}", show_keyboard=True)
                self.send_response(200)
                self.end_headers()
                return
            
            elif text == '/hide':
                # Показываем задачи для скрытия
                hidden_ids = get_hidden_tasks(user_id)
                tasks = get_my_tasks()
                visible = [t for t in tasks if t.get('id', '') not in (hidden_ids or [])]
                
                if not visible:
                    send_telegram_message(chat_id, "📋 Нет видимых задач для скрытия.", show_keyboard=True)
                else:
                    buttons = []
                    for t in visible[:10]:
                        short_name = t['name'][:30] + ('...' if len(t['name']) > 30 else '')
                        tags = f"[{', '.join(t.get('tags', []))}] " if t.get('tags') else ""
                        buttons.append([{"text": f"👁 {tags}{short_name}", "callback_data": f"hide_task_{t['id']}"}])
                    
                    if hidden_ids:
                        buttons.append([{"text": f"✅ Показать все скрытые ({len(hidden_ids)})", "callback_data": "unhide_all"}])
                    
                    msg = f"👁 *Скрыть задачи*\n\nНажми на задачу чтобы скрыть.\nСкрыто сейчас: *{len(hidden_ids)}*"
                    send_message_with_buttons(chat_id, msg, buttons)
                self.send_response(200)
                self.end_headers()
                return
            
            elif text == '/xp':
                from services.briefing import get_rpg_level
                from services.notion import get_user_xp
                xp_data = get_user_xp(user_id)
                xp = xp_data.get('xp', 0)
                title, next_t = get_rpg_level(xp)
                msg = f"<b>⚔️ Твой профиль, Шеф</b>\n\n{title}\n<b>{xp} XP</b>"
                if next_t:
                    msg += f"\nДо след. уровня: {next_t - xp} XP"
                send_telegram_message(chat_id, msg, use_html=True, show_keyboard=True)
                self.send_response(200)
                self.end_headers()
                return
            
            elif text == '/register_webhook':
                import requests as req
                from utils.config import CLICKUP_API_TOKEN, CLICKUP_TEAM_ID
                # Определяем URL webhook
                vercel_url = os.environ.get('VERCEL_URL', '')
                if not vercel_url:
                    send_telegram_message(chat_id, "❌ VERCEL_URL не установлен", show_keyboard=True)
                    self.send_response(200)
                    self.end_headers()
                    return
                
                webhook_url = f"https://{vercel_url}/api/clickup-webhook"
                headers = {"Authorization": CLICKUP_API_TOKEN, "Content-Type": "application/json"}
                payload = {
                    "endpoint": webhook_url,
                    "events": ["taskStatusUpdated"]
                }
                
                try:
                    resp = req.post(
                        f"https://api.clickup.com/api/v2/team/{CLICKUP_TEAM_ID}/webhook",
                        headers=headers,
                        json=payload,
                        timeout=10
                    )
                    if resp.status_code == 200:
                        wh_id = resp.json().get('id', '?')
                        send_telegram_message(chat_id, f"✅ Webhook зарегистрирован!\nID: `{wh_id}`\nURL: {webhook_url}", show_keyboard=True)
                    else:
                        send_telegram_message(chat_id, f"❌ Ошибка: {resp.status_code}\n{resp.text[:200]}", show_keyboard=True)
                except Exception as e:
                    send_telegram_message(chat_id, f"❌ Ошибка: {e}", show_keyboard=True)
                self.send_response(200)
                self.end_headers()
                return
            
            elif text == '/notes' or text == '📝 Заметки':
                send_telegram_message(chat_id, "🔎 Загружаю последние заметки...")
                latest_notes = get_latest_notes(5)
                if not latest_notes:
                    send_telegram_message(chat_id, "😔 Заметок пока нет.", show_keyboard=True)
                else:
                    # Формируем одно сообщение со списком
                    message_text = "📋 *Ваши последние заметки:*\n\n"
                    navigation_buttons = []
                    
                    for i, note in enumerate(latest_notes):
                        page_id = note['id']
                        title_parts = note.get('properties', {}).get('Name', {}).get('title', [])
                        
                        # Безопасное получение заголовка
                        if title_parts:
                            full_title = title_parts[0]['plain_text']
                        else:
                            full_title = "Без названия"
                            
                        # Обрезаем длинные заголовки для меню
                        button_title = (full_title[:20] + '..') if len(full_title) > 20 else full_title
                        
                        # Формируем строку списка (1. Заголовок)
                        message_text += f"*{i+1}. {full_title}*\n"
                        
                        # Добавляем кнопку навигации
                        # Используем callback note_menu_{page_id} для открытия меню действий
                        navigation_buttons.append([{"text": f"{i+1}. {button_title}", "callback_data": f"note_menu_{page_id}"}])
                    
                    send_message_with_buttons(chat_id, message_text, navigation_buttons)
                
                self.send_response(200)
                self.end_headers()
                return

            elif text.startswith('/search '):
                query = text.split(' ', 1)[1]
                if not query:
                    send_telegram_message(chat_id, "Пожалуйста, укажите, что нужно найти после команды /search.")
                    self.send_response(200)
                    self.end_headers()
                    return
                
                send_telegram_message(chat_id, f"🧠 Ищу по смыслу: *{query}*...")
                
                # 1. Ищем ID релевантных страниц в Pinecone
                found_ids = query_pinecone(query, top_k=3)
                
                if not found_ids:
                    send_telegram_message(chat_id, "😔 Ничего не найдено по вашему запросу.")
                    self.send_response(200)
                    self.end_headers()
                    return

                # 2. Собираем контент найденных страниц
                context = ""
                for page_id in found_ids:
                    try:
                        page_content = get_notion_page_content(page_id)
                        page_title = page_content.split('\n', 1)[0] if page_content else "Без названия"
                        context += f"--- Текст из заметки '{page_title}' ---\n{page_content}\n\n"
                    except Exception as e:
                        print(f"Не удалось получить контент для страницы {page_id}: {e}")

                if not context:
                    send_telegram_message(chat_id, "🤔 Нашел подходящие заметки, но не смог прочитать их содержимое.")
                    self.send_response(200)
                    self.end_headers()
                    return

                # 3. Отправляем контекст и вопрос в ИИ для генерации ответа
                answer = summarize_for_search(context, query)
                
                final_response = f"💡 *Вот что я нашел по вашему запросу:*\n\n{answer}"
                send_telegram_message(chat_id, final_response)
                
                self.send_response(200)
                self.end_headers()
                return
                
            elif text == '/undo':
                send_telegram_message(chat_id, "Пожалуйста, используйте кнопку '↩️ Отменить' под сообщением.")
                self.send_response(200)
                self.end_headers()
                return
            
            elif text.startswith('/edit'):
                # /edit <текст> — добавить текст в последнюю заметку
                edit_text = text[5:].strip()  # Убираем '/edit' и пробелы
                
                if not edit_text:
                    # Если текст не указан, показываем последнюю заметку с кнопками
                    last_page_id = get_last_created_page_id()
                    if last_page_id:
                        preview = get_page_preview(last_page_id)
                        buttons = [
                            [
                                {"text": "✏️ Переименовать", "callback_data": f"rename_page_{last_page_id}"},
                                {"text": "👁️ Просмотр", "callback_data": f"view_page_{last_page_id}"}
                            ],
                            [
                                {"text": "➕ Добавить текст", "callback_data": f"add_to_notion_{last_page_id}"},
                                {"text": "🗑️ Удалить", "callback_data": f"delete_notion_{last_page_id}"}
                            ]
                        ]
                        msg = f"📝 *Последняя заметка:*\n\n*{preview['title']}*\n_{preview['preview']}_"
                        send_message_with_buttons(chat_id, msg, buttons)
                    else:
                        send_telegram_message(chat_id, "❌ Нет заметок для редактирования.", show_keyboard=True)
                    self.send_response(200)
                    self.end_headers()
                    return
                
                # Получаем ID последней заметки
                last_page_id = get_last_created_page_id()
                
                if not last_page_id:
                    send_telegram_message(
                        chat_id, 
                        "❌ Не удалось найти последнюю заметку.\n\n"
                        "Возможно, лог действий пуст или не настроен."
                    )
                    self.send_response(200)
                    self.end_headers()
                    return
                
                # Сохраняем текст в user state и показываем кнопки выбора
                page_title = get_page_title(last_page_id)
                set_user_state(user_id, 'pending_edit', last_page_id, edit_text)
                
                buttons = [[
                    {"text": "➕ Просто добавить", "callback_data": f"edit_simple_{last_page_id}"},
                    {"text": "✨ Добавить + Полировка", "callback_data": f"edit_polish_{last_page_id}"}
                ]]
                
                msg = f"📝 Добавить в *{page_title}*:\n\n_{edit_text}_"
                send_message_with_buttons(chat_id, msg, buttons)
                
                self.send_response(200)
                self.end_headers()
                return
                
            # --- ЛОГИКА СОЗДАНИЯ НОВОЙ ЗАМЕТКИ (если это не команда) ---
            
            # Перехватываем текст/фото в режиме транскрипта
            active_mode = get_active_mode(user_id)
            if active_mode == 'transcript' and 'voice' not in message:
                buttons = [[{"text": "🔙 Выйти из режима", "callback_data": "exit_transcript"}]]
                send_message_with_buttons(
                    chat_id,
                    "🎙 Сейчас активен режим транскрипта.\n"
                    "Отправьте *голосовое сообщение* или нажмите кнопку ниже для выхода.",
                    buttons
                )
                self.send_response(200)
                self.end_headers()
                return
            
            text_to_process = None
            is_text_message = False
            photo_urls = []
            
            # Обработка фото
            if 'photo' in message:
                # Telegram присылает массив размеров, берём наибольший (последний)
                best_photo = message['photo'][-1]
                file_id = best_photo['file_id']
                
                try:
                    photo_url = get_telegram_file_url(file_id)
                    photo_urls.append(photo_url)
                    caption = message.get('caption', '').strip()
                    
                    if caption:
                        # Фото с подписью — создаём новую заметку
                        send_telegram_message(chat_id, "📸 Обрабатываю фото с подписью...")
                        text_to_process = caption
                    else:
                        # Фото без подписи — добавляем к последней заметке
                        last_page_id = get_last_created_page_id()
                        if last_page_id:
                            add_image_to_page(last_page_id, photo_url)
                            page_title = get_page_title(last_page_id)
                            send_telegram_message(chat_id, f"📸 Фото добавлено в *{page_title}*!", show_keyboard=True)
                        else:
                            send_telegram_message(chat_id, "❌ Нет заметок для добавления фото. Отправьте фото с подписью, чтобы создать новую.", show_keyboard=True)
                        self.send_response(200)
                        self.end_headers()
                        return
                        
                except Exception as e:
                    send_telegram_message(chat_id, f"❌ Ошибка обработки фото: {e}", show_keyboard=True)
                    self.send_response(200)
                    self.end_headers()
                    return
            
            elif 'voice' in message:
                # Проверяем активный режим транскрипта
                active_mode = get_active_mode(user_id)
                if active_mode == 'transcript':
                    # РЕЖИМ ТРАНСКРИПТА — только расшифровка, без AI и Notion
                    send_telegram_message(chat_id, "⏳ Распознаю речь...")
                    audio_bytes = download_telegram_file(message['voice']['file_id']).read()
                    transcript = transcribe_with_assemblyai(audio_bytes)
                    
                    if not transcript:
                        send_telegram_message(chat_id, "❌ Не удалось распознать речь. Попробуйте другое голосовое.")
                        self.send_response(200)
                        self.end_headers()
                        return
                    
                    # Чистый режим — убираем заполнители через AI
                    is_clean = get_transcript_clean(user_id)
                    if is_clean:
                        try:
                            transcript = clean_transcript(transcript)
                        except Exception as e:
                            print(f"Clean transcript error: {e}")
                            # Fallback: отдаём raw если чистка упала
                    
                    mode_icon = "✨" if is_clean else "📜"
                    
                    # Smart Chunking: разбиваем длинные транскрипты
                    max_len = 3900  # Запас от лимита 4096
                    if len(transcript) <= max_len:
                        msg = f"{mode_icon} *Транскрипт:*\n─────────────────\n{transcript}\n─────────────────"
                        buttons = [[{"text": "🔙 Выйти из режима", "callback_data": "exit_transcript"}]]
                        send_message_with_buttons(chat_id, msg, buttons)
                    else:
                        # Разбиваем по предложениям
                        sentences = transcript.replace('. ', '.\n').split('\n')
                        chunks = []
                        current_chunk = ""
                        for sentence in sentences:
                            if len(current_chunk) + len(sentence) + 1 > max_len:
                                if current_chunk:
                                    chunks.append(current_chunk.strip())
                                current_chunk = sentence
                            else:
                                current_chunk += " " + sentence if current_chunk else sentence
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        
                        total = len(chunks)
                        for i, chunk in enumerate(chunks):
                            header = f"{mode_icon} *Транскрипт ({i+1}/{total}):*" if total > 1 else f"{mode_icon} *Транскрипт:*"
                            msg = f"{header}\n─────────────────\n{chunk}\n─────────────────"
                            if i == total - 1:
                                buttons = [[{"text": "🔙 Выйти из режима", "callback_data": "exit_transcript"}]]
                                send_message_with_buttons(chat_id, msg, buttons)
                            else:
                                send_telegram_message(chat_id, msg)
                    
                    self.send_response(200)
                    self.end_headers()
                    return
                
                # Обычный режим — заметка через AI
                send_telegram_message(chat_id, "⏳ Распознаю речь...")
                audio_bytes = download_telegram_file(message['voice']['file_id']).read()
                text_to_process = transcribe_with_assemblyai(audio_bytes)
                if not text_to_process: 
                    send_telegram_message(chat_id, "❌ Не удалось распознать речь.")
            elif 'text' in message:
                is_text_message = True
                text_to_process = message['text']

            if text_to_process:
                status_message_id = None
                if is_text_message:
                    progress_bar = "⬜️⬜️⬜️⬜️⬜️⬜️ 0%"
                    status_message_id = send_initial_status_message(chat_id, f"⏳ Анализирую...\n`{progress_bar}`")

                if status_message_id:
                    progress_bar = "🟩🟩⬜️⬜️⬜️⬜️ 33%"
                    edit_telegram_message(chat_id, status_message_id, f"⏳ Анализирую...\n`{progress_bar}`")
                
                ai_data = process_with_ai(text_to_process)
                notion_title = ai_data.get('main_title', 'Новая заметка')
                notion_category = ai_data.get('category', 'Мысль')
                formatted_body = ai_data.get('formatted_body', text_to_process)
                is_reminder_only = ai_data.get('is_reminder_only', False)
                
                valid_events = [
                    event for event in ai_data.get('events', []) 
                    if event and event.get('title') and event.get('datetime_iso')
                ]
                
                # --- РЕЖИМ ТОЛЬКО НАПОМИНАНИЕ (без Notion) ---
                if is_reminder_only and valid_events:
                    if status_message_id:
                        progress_bar = "🟩🟩🟩🟩🟩🟩 99%"
                        edit_telegram_message(chat_id, status_message_id, f"⏳ Добавляю в календарь...\n`{progress_bar}`")
                    
                    created_events_info = []  # [(title, datetime_iso), ...]
                    created_events_links = []
                    for event in valid_events:
                        try:
                            gcal_result = create_google_calendar_event(
                                event['title'], 
                                formatted_body, 
                                event['datetime_iso']
                            )
                            if gcal_result and gcal_result.get('id'): 
                                log_last_action(gcal_event_id=gcal_result['id'])
                                created_events_links.append(gcal_result.get('html_link'))
                            created_events_info.append((event['title'], event['datetime_iso']))
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ *Ошибка при создании события '{event['title']}':*\n`{e}`")
                    
                    if created_events_info:
                        # Форматируем события с датой и временем
                        from datetime import datetime
                        events_text = []
                        for title, dt_iso in created_events_info:
                            try:
                                dt = datetime.fromisoformat(dt_iso)
                                formatted_dt = dt.strftime('%d.%m.%Y в %H:%M')
                                events_text.append(f"*{title}*\n   📆 {formatted_dt}")
                            except:
                                events_text.append(f"*{title}*")
                        
                        final_text = f"📅 *Напоминание создано!*\n\n" + "\n\n".join(events_text)
                        action_buttons = [[{"text": "↩️ Отменить", "callback_data": "undo_last_action"}]]
                        
                        if created_events_links and created_events_links[0]:
                            action_buttons.append([{"text": "📅 Открыть в календаре", "url": created_events_links[0]}])
                        
                        if status_message_id:
                            edit_telegram_message(chat_id, status_message_id, final_text, inline_buttons=action_buttons)
                        else:
                            send_message_with_buttons(chat_id, final_text, action_buttons)
                    
                    self.send_response(200)
                    self.end_headers()
                    return
                
                # --- ОБЫЧНЫЙ РЕЖИМ (Notion + календарь) ---
                if status_message_id:
                    progress_bar = "🟩🟩🟩🟩⬜️⬜️ 66%"
                    edit_telegram_message(chat_id, status_message_id, f"⏳ Сохраняю в Notion...\n`{progress_bar}`")

                notion_page_id = None
                try:
                    notion_page_id = create_notion_page(notion_title, formatted_body, notion_category)
                    if notion_page_id: 
                        log_last_action(notion_page_id=notion_page_id)
                        # Прикрепляем фото к созданной заметке
                        for photo_url in photo_urls:
                            try:
                                add_image_to_page(notion_page_id, photo_url)
                            except Exception as img_err:
                                print(f"Ошибка добавления фото: {img_err}")
                    if not is_text_message:
                        send_telegram_message(
                            chat_id, 
                            f"✅ *Заметка в Notion создана!*\n\n*Название:* {notion_title}\n*Категория:* {notion_category}", 
                            add_undo_button=True
                        )
                except Exception as e:
                    detailed_error = e.response.text if hasattr(e, 'response') else str(e)
                    final_text = f"❌ *Ошибка при создании заметки в Notion:*\n<pre>{detailed_error}</pre>"
                    if status_message_id: 
                        edit_telegram_message(chat_id, status_message_id, final_text, use_html=True)
                    else: 
                        send_telegram_message(chat_id, final_text, use_html=True)
                    self.send_response(200)
                    self.end_headers()
                    return

                created_events_titles = []
                created_events_links = []
                if valid_events:
                    if status_message_id:
                        progress_bar = "🟩🟩🟩🟩🟩🟩 99%"
                        edit_telegram_message(chat_id, status_message_id, f"⏳ Добавляю в календарь...\n`{progress_bar}`")
                    for event in valid_events:
                        try:
                            gcal_result = create_google_calendar_event(
                                event['title'], 
                                formatted_body, 
                                event['datetime_iso']
                            )
                            if gcal_result and gcal_result.get('id'): 
                                log_last_action(gcal_event_id=gcal_result['id'])
                                created_events_links.append(gcal_result.get('html_link'))
                            created_events_titles.append(event['title'])
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ *Ошибка при создании события '{event['title']}':*\n`{e}`")
                
                final_report_text = f"✅ *Заметка создана!*\n\n📋 *{notion_title}*\n_{formatted_body[:100]}..._" if len(formatted_body) > 100 else f"✅ *Заметка создана!*\n\n📋 *{notion_title}*\n_{formatted_body}_"
                final_report_text += f"\n\n_Категория: {notion_category}_"
                
                if created_events_titles:
                    final_report_text += "\n\n📅 *Добавлено в календарь:*\n- " + "\n- ".join(created_events_titles)
                
                # Создаём inline кнопки для действий
                action_buttons = [
                    [
                        {"text": "✏️ Переименовать", "callback_data": f"rename_page_{notion_page_id}"},
                        {"text": "👁️ Просмотр", "callback_data": f"view_page_{notion_page_id}"}
                    ],
                    [
                        {"text": "➕ Добавить", "callback_data": f"add_to_notion_{notion_page_id}"},
                        {"text": "↩️ Отменить", "callback_data": "undo_last_action"}
                    ]
                ]
                
                # Добавляем кнопку календаря если есть события
                if created_events_links and created_events_links[0]:
                    action_buttons.append([
                        {"text": "📅 Открыть в календаре", "url": created_events_links[0]}
                    ])
                
                if status_message_id:
                    # Редактируем существующее сообщение с прогресс-баром
                    edit_telegram_message(chat_id, status_message_id, final_report_text, inline_buttons=action_buttons)
                else:
                    # Отправляем новое сообщение с кнопками
                    send_message_with_buttons(chat_id, final_report_text, action_buttons)
        except Exception as e:
            if chat_id:
                send_telegram_message(chat_id, f"🤯 *Произошла глобальная ошибка!*\nПожалуйста, проверьте логи Vercel.\n`{e}`")
            print(f"Произошла глобальная ошибка: {e}")
        
        self.send_response(200)
        self.end_headers()
        return
