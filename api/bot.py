# -*- coding: utf-8 -*-
"""Telegram Bot Handler - Main entry point for Vercel serverless function."""
import json
import requests
from http.server import BaseHTTPRequestHandler

# --- Imports from utils ---
from utils.config import (
    validate_env_vars,
    TELEGRAM_TOKEN,
    ALLOWED_TELEGRAM_ID,
    DEFAULT_TIMEOUT
)

# --- Imports from services ---
from services.telegram import (
    download_telegram_file,
    send_telegram_message,
    send_initial_status_message,
    edit_telegram_message
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
    get_user_state
)
from services.calendar import (
    create_google_calendar_event,
    delete_gcal_event
)
from services.ai import (
    transcribe_with_assemblyai,
    process_with_deepseek,
    summarize_for_search
)
from services.pinecone_svc import (
    upsert_to_pinecone,
    query_pinecone
)

# Validate environment variables at startup
validate_env_vars()


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
                requests.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery?callback_query_id={callback_query_id}", 
                    timeout=DEFAULT_TIMEOUT
                )

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
            
            # ПРОВЕРКА СОСТОЯНИЯ: не ждем ли мы текст для добавления?
            user_state = get_user_state(user_id)
            if user_state:
                if user_state.get('state') == 'awaiting_add_text':
                    page_id_to_edit = user_state['page_id']
                    text_to_add = message.get('text', '')
                    if text_to_add:
                        add_to_notion_page(page_id_to_edit, text_to_add)
                        send_telegram_message(chat_id, "✅ Текст успешно добавлен в заметку!")
                    else:
                        send_telegram_message(chat_id, "Отмена. Получено пустое сообщение.")
                    self.send_response(200)
                    self.end_headers()
                    return
            
            text = message.get('text', '')

            if text == '/index_all':
                send_telegram_message(chat_id, "Начинаю полную индексацию всех заметок. Это может занять время...")
                all_notes = get_latest_notes(100)
                for note in all_notes:
                    page_id = note['id']
                    page_content = get_notion_page_content(page_id)
                    upsert_to_pinecone(page_id, page_content)
                send_telegram_message(chat_id, f"✅ Готово! Проиндексировано {len(all_notes)} заметок.")
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
                
                final_report_text = f"✅ *Заметка «{notion_title}» создана!*\n_Категория: {notion_category}_"
                if created_events_titles:
                    final_report_text += "\n\n📅 *Добавлено в календарь:*\n- " + "\n- ".join(created_events_titles)
                if status_message_id:
                    edit_telegram_message(chat_id, status_message_id, final_report_text, add_undo_button=True)
                elif created_events_titles:
                    send_telegram_message(
                        chat_id, 
                        f"📅 *Добавлено {len(created_events_titles)} события в Календарь:*\n- " + "\n- ".join(created_events_titles), 
                        add_undo_button=True
                    )
        except Exception as e:
            if chat_id:
                send_telegram_message(chat_id, f"🤯 *Произошла глобальная ошибка!*\nПожалуйста, проверьте логи Vercel.\n`{e}`")
            print(f"Произошла глобальная ошибка: {e}")
        
        self.send_response(200)
        self.end_headers()
        return
