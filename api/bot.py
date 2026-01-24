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
        get_and_delete_last_log,
        log_last_action,
        set_user_state,
        get_user_state,
        get_last_created_page_id,
        get_page_title,
        get_page_preview,
        replace_page_content,
        rename_page
    )
    from services.calendar import (
        create_google_calendar_event,
        delete_gcal_event
    )
    from services.ai import (
        transcribe_with_assemblyai,
        process_with_deepseek,
        summarize_for_search,
        polish_content
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
                    try:
                        delete_notion_page(page_id_to_delete)
                        send_telegram_message(chat_id, f"🗑️ Заметка удалена.")
                    except Exception as e:
                        send_telegram_message(chat_id, f"❌ Не удалось удалить заметку. Ошибка: {e}")

                elif callback_data.startswith('add_to_notion_'):
                    page_id = callback_data.split('_', 3)[3]
                    set_user_state(str(chat_id), 'awaiting_add_text', page_id)
                    send_telegram_message(chat_id, "▶️ Введите текст, который нужно *добавить* в конец заметки:")
                
                elif callback_data.startswith('rename_page_'):
                    page_id = callback_data.replace('rename_page_', '')
                    set_user_state(str(chat_id), 'awaiting_rename', page_id)
                    send_telegram_message(chat_id, "✏️ Введите новое название заметки:")
                
                elif callback_data.startswith('view_page_'):
                    page_id = callback_data.replace('view_page_', '')
                    try:
                        title = get_page_title(page_id)
                        content = get_notion_page_content(page_id)
                        # Ограничиваем длину для Telegram (4096 символов)
                        if len(content) > 3500:
                            content = content[:3500] + "\n\n... _(текст обрезан)_"
                        send_telegram_message(chat_id, f"📋 *{title}*\n\n{content}")
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
            
            # ОБРАБОТКА КНОПОК КЛАВИАТУРЫ
            if text == "📝 Заметки":
                text = "/notes"  # Перенаправляем на существующую логику
            elif text == "🔍 Поиск":
                set_user_state(user_id, 'awaiting_search', None)
                send_telegram_message(chat_id, "🔍 Введите поисковый запрос:")
                self.send_response(200)
                self.end_headers()
                return
            elif text == "✏️ Изменить":
                # Показываем последнюю заметку с кнопками
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
                    msg = f"📋 *{preview['title']}*\n\n_{preview['preview']}_"
                    send_message_with_buttons(chat_id, msg, buttons)
                else:
                    send_telegram_message(chat_id, "❌ Нет заметок для редактирования.", show_keyboard=True)
                self.send_response(200)
                self.end_headers()
                return
            elif text == "↩️ Отмена":
                text = "/undo"

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
            if text == '/notes':
                send_telegram_message(chat_id, "🔎 Ищу 3 последние заметки...")
                latest_notes = get_latest_notes(3)
                if not latest_notes:
                    send_telegram_message(chat_id, "😔 Заметок пока нет.")
                else:
                    send_telegram_message(chat_id, f"👇 Вот что я нашел:")
                    for note in latest_notes:
                        page_id = note['id']
                        title_parts = note.get('properties', {}).get('Name', {}).get('title', [])
                        page_title = title_parts[0]['plain_text'] if title_parts else "Без названия"
                        keyboard = {"inline_keyboard": [[ 
                            {"text": "➕ Добавить", "callback_data": f"add_to_notion_{page_id}"}, 
                            {"text": "🗑️ Удалить", "callback_data": f"delete_notion_{page_id}"} 
                        ]]}
                        message_text = f"*{page_title}*"
                        payload = {
                            'chat_id': chat_id, 
                            'text': message_text, 
                            'parse_mode': 'Markdown', 
                            'reply_markup': json.dumps(keyboard)
                        }
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                            json=payload, 
                            timeout=DEFAULT_TIMEOUT
                        )
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
            text_to_process = None
            is_text_message = False
            if 'voice' in message:
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
                
                ai_data = process_with_deepseek(text_to_process)
                notion_title = ai_data.get('main_title', 'Новая заметка')
                notion_category = ai_data.get('category', 'Мысль')
                formatted_body = ai_data.get('formatted_body', text_to_process)
                
                if status_message_id:
                    progress_bar = "🟩🟩🟩🟩⬜️⬜️ 66%"
                    edit_telegram_message(chat_id, status_message_id, f"⏳ Сохраняю в Notion...\n`{progress_bar}`")

                try:
                    notion_page_id = create_notion_page(notion_title, formatted_body, notion_category)
                    if notion_page_id: 
                        log_last_action(notion_page_id=notion_page_id)
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

                valid_events = [
                    event for event in ai_data.get('events', []) 
                    if event and event.get('title') and event.get('datetime_iso')
                ]
                created_events_titles = []
                if valid_events:
                    if status_message_id:
                        progress_bar = "🟩🟩🟩🟩🟩🟩 99%"
                        edit_telegram_message(chat_id, status_message_id, f"⏳ Добавляю в календарь...\n`{progress_bar}`")
                    for event in valid_events:
                        try:
                            gcal_event_id = create_google_calendar_event(
                                event['title'], 
                                formatted_body, 
                                event['datetime_iso']
                            )
                            if gcal_event_id: 
                                log_last_action(gcal_event_id=gcal_event_id)
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
                
                if status_message_id:
                    # Редактируем существующее сообщение с прогресс-баром
                    edit_telegram_message(chat_id, status_message_id, final_report_text, add_undo_button=True)
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
