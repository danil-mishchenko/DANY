# -*- coding: utf-8 -*-
"""Message Handler for Telegram Bot."""

import re
from datetime import datetime, timezone, timedelta

from services.telegram import (
    send_telegram_message,
    send_message_with_buttons,
    send_initial_status_message,
    edit_telegram_message,
    download_telegram_file,
    get_telegram_file_url
)
from services.notion import (
    create_notion_page,
    add_image_to_page,
    add_to_notion_page,
    get_notion_page_content,
    get_page_title,
    get_page_preview,
    rename_page,
    replace_page_content,
    get_latest_notes,
    search_notion_pages
)
from services.calendar import create_google_calendar_event, get_calendar_events_for_range
from services.state import (
    log_last_action,
    set_user_state,
    get_user_state,
    get_last_created_page_id,
    get_active_mode,
    set_active_mode,
    get_transcript_clean,
    get_transcript_single_mode,
    save_temp_transcript,
    append_to_transcript_buffer,
    get_note_content_cache,
    set_note_content_cache,
    get_note_metadata
)
from services.ai import (
    transcribe_with_assemblyai,
    clean_transcript,
    process_with_ai,
    summarize_for_search,
    integrate_contextually,
    expand_search_query
)
from services.pinecone_svc import (
    query_pinecone_parent_child,
    apply_temporal_decay,
    upsert_to_pinecone,
    delete_from_pinecone
)

def format_with_timecodes(words: list) -> str:
    """Группирует слова из AssemblyAI в абзацы по предложениям и добавляет таймкоды."""
    if not words:
        return ""
    
    formatted = []
    current_chunk = []
    chunk_start = words[0]['start']
    
    for word in words:
        if chunk_start is None:
            chunk_start = word.get('start', 0)
            
        current_chunk.append(word['text'])
        
        # Start new line if sentence ends
        if word['text'].endswith(('.', '?', '!')):
            text = " ".join(current_chunk)
            
            safe_start = chunk_start if chunk_start is not None else 0
            minutes = safe_start // 60000
            seconds = (safe_start % 60000) // 1000
            
            timecode = f"[{minutes:02d}:{seconds:02d}]"
            formatted.append(f"{timecode} {text}")
            current_chunk = []
            chunk_start = None
            
    if current_chunk:
        text = " ".join(current_chunk)
        safe_start = chunk_start if chunk_start is not None else 0
        minutes = safe_start // 60000
        seconds = (safe_start % 60000) // 1000
        timecode = f"[{minutes:02d}:{seconds:02d}]"
        formatted.append(f"{timecode} {text}")
        
    return "\n\n".join(formatted)


def update_status(chat_id: str, message_id: int, title: str, percentage: int):
    """Обновляет сообщение-статус с красивым прогресс-баром."""
    if not message_id:
        return
    # Строим прогресс-бар длины 10 из 🟩 и ⬜️
    filled = max(0, min(10, percentage // 10))
    empty = 10 - filled
    bar = "🟩" * filled + "⬜️" * empty
    
    text = f"⏳ <b>{title}</b>\n<code>{bar}  {percentage}%</code>"
    edit_telegram_message(chat_id, message_id, text, use_html=True)


def handle_message(chat_id: int, user_id: str, text: str, message: dict):
    """Обработка обычных сообщений, состояний ожидания и медиафайлов."""
    status_message_id = None
    
    # Проверяем команду контекстного ИИ-дополнения "Дд " / "дд "
    raw_text = text.strip() if text else ""
    if raw_text.lower().startswith("дд "):
        command_body = raw_text[3:].strip()
        if command_body:
            from services.state import redis_client
            
            # Redis Lock для предотвращения одновременных изменений
            lock_key = f"dany:user:{user_id}:write_lock"
            if redis_client.get(lock_key):
                send_telegram_message(chat_id, "⏳ Предыдущее изменение еще обрабатывается. Пожалуйста, подождите...")
                return
            
            redis_client.setex(lock_key, 3, "1")
            status_id = send_initial_status_message(chat_id, "⏳ <b>Поиск последней заметки...</b>\n<code>⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️  0%</code>", use_html=True)
            
            try:
                latest_notes = get_latest_notes(1)
                if not latest_notes:
                    edit_telegram_message(chat_id, status_id, "❌ Не найдено ни одной заметки для дополнения.")
                    return
                
                note = latest_notes[0]
                page_id = note['id']
                title_parts = note.get('properties', {}).get('Name', {}).get('title', [])
                page_title = title_parts[0]['plain_text'] if title_parts else "Без названия"
                
                update_status(chat_id, status_id, f"Чтение заметки {page_title}...", 25)
                old_content = get_notion_page_content(page_id)
                
                update_status(chat_id, status_id, "Интеграция с ИИ...", 50)
                new_content = integrate_contextually(old_content, command_body)
                
                # Сохраняем оригинальный контент перед перезаписью!
                log_last_action(user_id=user_id, action='edit', notion_page_id=page_id, old_markdown=old_content)
                
                update_status(chat_id, status_id, "Сохранение в Notion...", 75)
                replace_page_content(page_id, new_content)
                
                update_status(chat_id, status_id, "Векторизация...", 90)
                try:
                    import threading
                    full_text_for_embedding = f"Заголовок: {page_title}\nСодержимое: {new_content}"
                    t = threading.Thread(target=upsert_to_pinecone, args=(page_id, full_text_for_embedding))
                    t.daemon = True
                    t.start()
                    t.join(timeout=0.2)
                except Exception as pinecone_err:
                    print(f"Ошибка индексации Pinecone при Дд: {pinecone_err}")
                
                buttons = [
                    [
                        {"text": "👁️ Просмотр", "callback_data": f"view_page_{page_id}"},
                        {"text": "✏️ Переименовать", "callback_data": f"rename_page_{page_id}"}
                    ],
                    [
                        {"text": "➕ Добавить", "callback_data": f"add_to_notion_{page_id}"},
                        {"text": "↩️ Отменить", "callback_data": "undo_last_action"}
                    ]
                ]
                edit_telegram_message(chat_id, status_id, f"✅ Встроено в заметку *{page_title}*!", inline_buttons=buttons)
            except Exception as dany_err:
                print(f"Ошибка команды Дд: {dany_err}")
                edit_telegram_message(chat_id, status_id, f"❌ Ошибка встраивания информации: {dany_err}")
            finally:
                try:
                    redis_client.delete(lock_key)
                except Exception:
                    pass
            return
    
    # 1. ПРОВЕРКА СОСТОЯНИЯ: не ждем ли мы текст для добавления/переименования/поиска?
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
            return
        
        elif state_type == 'awaiting_search':
            is_audio_msg = False
            aud_file_id = None
            if 'voice' in message:
                is_audio_msg = True
                aud_file_id = message['voice']['file_id']
            elif 'audio' in message:
                is_audio_msg = True
                aud_file_id = message['audio']['file_id']
            elif 'video_note' in message:
                is_audio_msg = True
                aud_file_id = message['video_note']['file_id']
            elif 'video' in message:
                is_audio_msg = True
                aud_file_id = message['video']['file_id']
            elif 'document' in message:
                mime_type = message['document'].get('mime_type', '')
                if mime_type.startswith('audio/') or mime_type.startswith('video/'):
                    is_audio_msg = True
                    aud_file_id = message['document']['file_id']

            query = ""
            if is_audio_msg and aud_file_id:
                send_telegram_message(chat_id, "⏳ Расшифровываю голосовой запрос...")
                try:
                    audio_bytes = download_telegram_file(aud_file_id).read()
                    transcript_data = transcribe_with_assemblyai(audio_bytes)
                    query = transcript_data.get('text', '').strip() if transcript_data else ""
                except Exception as ae:
                    print(f"Ошибка голосового поиска: {ae}")
                    send_telegram_message(chat_id, f"❌ Ошибка расшифровки голоса: {ae}", show_keyboard=True)
                    set_user_state(user_id, None, None)
                    return
            else:
                query = message.get('text', '').strip()

            if query:
                send_telegram_message(chat_id, f"🧠 Ищу по смыслу: *{query}*...")
                
                # 1. Расширение запроса через LLM
                try:
                    expanded_queries = expand_search_query(query)
                    print(f"[search] Расширенные запросы: {expanded_queries}")
                except Exception as ee:
                    print(f"Ошибка расширения запроса: {ee}")
                    expanded_queries = [query]
                    
                # 2. Поиск чанков в Pinecone для всех запросов
                pinecone_matches = {}
                for q in expanded_queries:
                    try:
                        matches = query_pinecone_parent_child(q, top_k=20)
                        for m in matches:
                            pid = m['id']
                            score = m['score']
                            if pid not in pinecone_matches:
                                pinecone_matches[pid] = score
                            else:
                                pinecone_matches[pid] = max(pinecone_matches[pid], score)
                    except Exception as pe:
                        print(f"Ошибка поиска в Pinecone по запросу '{q}': {pe}")
                        
                # 3. Точный гибридный поиск по Notion
                try:
                    notion_results = search_notion_pages(query)
                    for page in notion_results:
                        if 'id' in page:
                            pid = page['id']
                            # Даем максимальный базовый скор 1.0 за точное текстовое совпадение
                            if pid not in pinecone_matches:
                                pinecone_matches[pid] = 1.0
                            else:
                                pinecone_matches[pid] = max(pinecone_matches[pid], 1.0)
                except Exception as ne:
                    print(f"Ошибка точного поиска в Notion: {ne}")
                    
                # Формируем список матчей
                matches_list = [{'id': pid, 'score': score} for pid, score in pinecone_matches.items()]
                
                if not matches_list:
                    send_telegram_message(chat_id, "😔 Ничего не найдено.", show_keyboard=True)
                else:
                    # 4. Собираем метаданные из Redis для временного затухания
                    note_meta_dates = {}
                    for match in matches_list:
                        pid = match['id']
                        meta = get_note_metadata(pid)
                        if meta and meta.get('last_edited_time'):
                            try:
                                dt_str = meta['last_edited_time'].replace('Z', '+00:00')
                                note_meta_dates[pid] = datetime.fromisoformat(dt_str)
                            except Exception as de:
                                print(f"Ошибка парсинга даты для {pid}: {de}")
                                
                    # 5. Применяем временное затухание релевантности (Recency-Bias)
                    matches_list = apply_temporal_decay(matches_list, note_meta_dates)
                    
                    # 6. Отбираем топ-15 заметок (Deep Analysis top_k=15)
                    top_matches = matches_list[:15]
                    found_ids = [m['id'] for m in top_matches]
                    
                    # 7. Интеграция с Google Календарем (Calendar Integration)
                    calendar_context = ""
                    temporal_keywords = ["завтра", "сегодня", "выходны", "план", "встреч", "календар", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
                    has_temporal = any(kw in query.lower() for kw in temporal_keywords)
                    
                    if has_temporal:
                        try:
                            import pytz
                            from utils.config import USER_TIMEZONE
                            tz = pytz.timezone(USER_TIMEZONE)
                            now = datetime.now(tz)
                            
                            # По умолчанию берем диапазон: от начала сегодняшнего дня на ближайшие 7 дней
                            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                            end_dt = start_dt + timedelta(days=7)
                            
                            # Если конкретно "завтра"
                            if "завтра" in query.lower():
                                start_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                                end_dt = start_dt + timedelta(days=1)
                            # Если "сегодня"
                            elif "сегодня" in query.lower():
                                start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                                end_dt = start_dt + timedelta(days=1)
                            # Если "выходные"
                            elif "выходны" in query.lower():
                                days_to_sat = (5 - now.weekday()) % 7
                                start_dt = (now + timedelta(days=days_to_sat)).replace(hour=0, minute=0, second=0, microsecond=0)
                                end_dt = start_dt + timedelta(days=2)
                                
                            events = get_calendar_events_for_range(start_dt.isoformat(), end_dt.isoformat())
                            if events:
                                calendar_context += "\n--- СОБЫТИЯ ИЗ GOOGLE КАЛЕНДАРЯ ---\n"
                                for ev in events:
                                    calendar_context += f"📅 {ev['summary']} | Время: {ev['start']} - {ev['end']}\n"
                                    if ev.get('description'):
                                        calendar_context += f"Описание: {ev['description']}\n"
                                calendar_context += "---------------------------------\n\n"
                                print(f"[search] Календарь подмешан в контекст RAG.")
                        except Exception as ce:
                            print(f"Ошибка при получении данных календаря: {ce}")
                            
                    # 8. Сбор полного контекста из заметок (из кэша Redis с fallback на Notion)
                    context = ""
                    if calendar_context:
                        context += calendar_context
                        
                    errors = []
                    source_buttons = []
                    
                    for page_id in found_ids:
                        try:
                            # Получаем Markdown-контент из Redis кэша
                            page_content = get_note_content_cache(page_id)
                            if not page_content:
                                page_content = get_notion_page_content(page_id)
                                set_note_content_cache(page_id, page_content)
                                
                            # Получаем метаданные (заголовок, категорию, даты) из Redis кэша
                            meta = get_note_metadata(page_id)
                            if meta:
                                page_title = meta.get('title', 'Без названия')
                                category = meta.get('category', 'Мысль')
                                created_time = meta.get('created_time', '')
                                last_edited_time = meta.get('last_edited_time', '')
                            else:
                                page_title = page_content.split('\n', 1)[0] if page_content else "Без названия"
                                page_title = re.sub(r'^[#*_\s]+', '', page_title).strip()
                                category = "Мысль"
                                created_time = "Неизвестно"
                                last_edited_time = "Неизвестно"
                                
                            button_title = (page_title[:20] + '..') if len(page_title) > 20 else page_title
                            
                            # Форматируем полноценные метаданные (Feature 5)
                            context += (
                                f"📌 [Заметка: {page_title}]\n"
                                f"🏷 Категория: {category}\n"
                                f"📅 Создана: {created_time} | Изменена: {last_edited_time}\n"
                                f"📝 Содержимое:\n{page_content}\n"
                                f"{'='*40}\n\n"
                            )
                            
                            source_buttons.append({"text": f"📖 {button_title}", "callback_data": f"note_menu_{page_id}"})
                        except Exception as e:
                            err_desc = f"Page `{page_id}`: `{e}`"
                            errors.append(err_desc)
                            print(f"Не удалось получить контент для страницы {page_id}: {e}")
                            
                    if context:
                        # 9. Генерация ответа ИИ
                        answer = summarize_for_search(context, query)
                        
                        # Группируем кнопки-источники в ряды по 2 кнопки
                        inline_buttons = []
                        for i in range(0, len(source_buttons), 2):
                            inline_buttons.append(source_buttons[i:i+2])
                            
                        send_message_with_buttons(chat_id, f"💡 <b>Вот что я нашел по вашему запросу:</b>\n\n{answer}", inline_buttons, use_html=True)
                    else:
                        err_text = "\n".join(errors)
                        send_telegram_message(chat_id, f"🤔 Нашел подходящие заметки, но не смог прочитать их содержимое.\n\n*Ошибки:*\n{err_text}", show_keyboard=True)
            else:
                send_telegram_message(chat_id, "Отмена. Пустой запрос.", show_keyboard=True)
            set_user_state(user_id, None, None)
            return

    # 2. ОПРЕДЕЛЕНИЕ ТИПА СООБЩЕНИЯ (АУДИО/ВИДЕО)
    is_audio_message = False
    audio_file_id = None
    
    if 'voice' in message:
        is_audio_message = True
        audio_file_id = message['voice']['file_id']
    elif 'audio' in message:
        is_audio_message = True
        audio_file_id = message['audio']['file_id']
    elif 'video_note' in message:
        is_audio_message = True
        audio_file_id = message['video_note']['file_id']
    elif 'video' in message:
        is_audio_message = True
        audio_file_id = message['video']['file_id']
    elif 'document' in message:
        mime_type = message['document'].get('mime_type', '')
        if mime_type.startswith('audio/') or mime_type.startswith('video/'):
            is_audio_message = True
            audio_file_id = message['document']['file_id']

    # 3. Перехватываем текст/фото в режиме транскрипта
    active_mode = get_active_mode(user_id)
    if active_mode == 'transcript' and not is_audio_message:
        buttons = [[{"text": "🔙 Выйти из режима", "callback_data": "exit_transcript"}]]
        send_message_with_buttons(
            chat_id,
            "🎙 Сейчас активен режим транскрипта.\n"
            "Отправьте *аудио, голосовое или кружочек* или нажмите кнопку ниже для выхода.",
            buttons
        )
        return
    
    # 4. Обработка фото
    text_to_process = None
    is_text_message = False
    photo_urls = []
    
    if 'photo' in message:
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
                return
                
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка обработки фото: {e}", show_keyboard=True)
            return
    
    # 5. Обработка аудио в режиме транскрипта или обычном
    elif is_audio_message:
        if active_mode == 'transcript':
            # РЕЖИМ ТРАНСКРИПТА — только расшифровка, без AI и Notion
            send_telegram_message(chat_id, "⏳ Распознаю аудио...")
            audio_bytes = download_telegram_file(audio_file_id).read()
            transcript_data = transcribe_with_assemblyai(audio_bytes)
            transcript = transcript_data.get('text') if transcript_data else None
            
            if not transcript:
                send_telegram_message(chat_id, "❌ Не удалось распознать речь. Попробуйте другой файл.")
                return
            
            is_single_mode = get_transcript_single_mode(user_id)
            is_clean = get_transcript_clean(user_id)
            mode_icon = "✨" if is_clean else "📜"
            
            # SINGLE MODE
            if is_single_mode:
                words = transcript_data.get('words', [])
                if words:
                    transcript = format_with_timecodes(words)
                    
                # Чистый режим поверх таймкодов
                if is_clean:
                    try:
                        transcript = clean_transcript(transcript)
                    except Exception as e:
                        print(f"Clean transcript error: {e}")
                        
                log_id = save_temp_transcript(user_id, transcript)
                buttons = []
                if log_id:
                    buttons.append([
                        {"text": "💾 В Notion", "callback_data": f"save_transcript_{log_id}"},
                        {"text": "📊 Резюме", "callback_data": f"summarize_transcript_{log_id}"}
                    ])
                buttons.append([{"text": "🔙 Выйти из режима", "callback_data": "exit_transcript"}])
                
                max_len = 3900
                if len(transcript) <= max_len:
                    send_message_with_buttons(chat_id, f"✅ *Одиночный транскрипт ({mode_icon}):*\n\n{transcript}", buttons, reply_to_message_id=message.get('message_id'))
                else:
                    preview = transcript[:max_len] + "\n\n... _(Текст обрезан)_"
                    send_message_with_buttons(chat_id, f"✅ *Одиночный транскрипт ({mode_icon}):*\n\n{preview}", buttons, reply_to_message_id=message.get('message_id'))
                    
                return
            
            # MULTI MODE
            if is_clean:
                try:
                    transcript = clean_transcript(transcript)
                except Exception as e:
                    print(f"Clean transcript error: {e}")
                    
            # Добавляем в буфер
            new_buffer = append_to_transcript_buffer(user_id, transcript)
            
            if new_buffer:
                parts_count = new_buffer.count("\n\n---\n\n")
                
                preview_text = transcript
                if len(transcript) > 500:
                    preview_text = transcript[:500] + "..."
                    
                msg = (
                    f"{mode_icon} *Распознана часть {parts_count}:*\n_{preview_text}_\n\n"
                    f"🗣 Отправьте следующее аудио, чтобы дополнить, или нажмите кнопку ниже."
                )
                
                buttons = [
                    [
                        {"text": "✅ Завершить и показать все", "callback_data": "transcript_finish"}
                    ],
                    [
                        {"text": "🗑 Очистить", "callback_data": "transcript_clear"},
                        {"text": "🔙 Выйти", "callback_data": "exit_transcript"}
                    ]
                ]
                send_message_with_buttons(chat_id, msg, buttons)
            else:
                send_telegram_message(chat_id, "❌ Ошибка буферизации.")
            return
        
        # Обычный режим — заметка через AI
        status_message_id = send_initial_status_message(chat_id, "⏳ <b>Запускаю распознавание...</b>\n<code>⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️  0%</code>", use_html=True)
        update_status(chat_id, status_message_id, "Загрузка аудио...", 10)
        audio_bytes = download_telegram_file(audio_file_id).read()
        update_status(chat_id, status_message_id, "Распознавание речи...", 20)
        transcript_data = transcribe_with_assemblyai(audio_bytes)
        text_to_process = transcript_data.get('text') if transcript_data else None
        if not text_to_process: 
            if status_message_id:
                edit_telegram_message(chat_id, status_message_id, "❌ <b>Не удалось распознать речь.</b>", use_html=True)
            else:
                send_telegram_message(chat_id, "❌ Не удалось распознать речь.")
            return
            
    elif 'text' in message:
        is_text_message = True
        text_to_process = message['text']

    # 6. Обработка извлеченного текста (Notion + Календарь)
    if text_to_process:
        if status_message_id is None:
            status_message_id = send_initial_status_message(chat_id, "⏳ <b>Запускаю обработку...</b>\n<code>⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️  0%</code>", use_html=True)
        
        update_status(chat_id, status_message_id, "Анализирую текст ИИ...", 35)
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
            update_status(chat_id, status_message_id, "Добавляю в календарь...", 80)
            
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
                events_text = []
                for title, dt_iso in created_events_info:
                    try:
                        dt = datetime.fromisoformat(dt_iso)
                        formatted_dt = dt.strftime('%d.%m.%Y в %H:%M')
                        events_text.append(f"*{title}*\n   📆 {formatted_dt}")
                    except (ValueError, TypeError):
                        events_text.append(f"*{title}*")
                
                final_text = f"📅 *Напоминание создано!*\n\n" + "\n\n".join(events_text)
                action_buttons = [[{"text": "↩️ Отменить", "callback_data": "undo_last_action"}]]
                
                if created_events_links and created_events_links[0]:
                    action_buttons.append([{"text": "📅 Открыть в календаре", "url": created_events_links[0]}])
                
                if status_message_id:
                    edit_telegram_message(chat_id, status_message_id, final_text, inline_buttons=action_buttons)
                else:
                    send_message_with_buttons(chat_id, final_text, action_buttons)
            return
        
        # --- ОБЫЧНЫЙ РЕЖИМ (Notion + календарь) ---

        notion_page_id = None
        try:
            update_status(chat_id, status_message_id, "Создаю страницу в Notion...", 55)
            notion_page_id = create_notion_page(notion_title, formatted_body, notion_category)
            if notion_page_id: 
                log_last_action(notion_page_id=notion_page_id)
                for photo_url in photo_urls:
                    try:
                        update_status(chat_id, status_message_id, "Добавляю фото в Notion...", 70)
                        add_image_to_page(notion_page_id, photo_url)
                    except Exception as img_err:
                        print(f"Ошибка добавления фото: {img_err}")
        except Exception as e:
            detailed_error = e.response.text if hasattr(e, 'response') else str(e)
            err_msg_lower = str(e).lower()
            if "timeout" in err_msg_lower or "timed out" in err_msg_lower or "readtimedouterror" in err_msg_lower:
                final_text = (
                    "⚠️ *Сохранение в Notion заняло больше времени, чем обычно!*\n\n"
                    "Из-за ограничений серверов мы завершили ожидание ответа, но страница "
                    "*скорее всего успешно создалась* в Notion.\n"
                    "Пожалуйста, проверьте её в списке заметок (команда /notes) или через поиск!"
                )
                use_html_flag = False
            else:
                final_text = f"❌ *Ошибка при создании заметки в Notion:*\n<pre>{detailed_error}</pre>"
                use_html_flag = True
                
            if status_message_id: 
                edit_telegram_message(chat_id, status_message_id, final_text, use_html=use_html_flag)
            else: 
                send_telegram_message(chat_id, final_text, use_html=use_html_flag)
            return

        created_events_titles = []
        created_events_links = []
        if valid_events:
            update_status(chat_id, status_message_id, "Добавляю события в календарь...", 80)
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
        
        update_status(chat_id, status_message_id, "Индексирую для поиска...", 95)
        
        # Очищаем превью от Markdown и HTML-тегов для обеспечения совместимости с парсером Telegram
        clean_preview = formatted_body
        # Удаляем HTML-теги
        clean_preview = re.sub(r'<[^>]+>', '', clean_preview)
        # Удаляем фоновые цвета ИИ {color="..."} и {{color="..."}}
        clean_preview = re.sub(r'\{+color=[^}]+\}+', '', clean_preview)
        # Удаляем символы форматирования Markdown
        clean_preview = re.sub(r'[*_`~#]', '', clean_preview)
        # Удаляем To-Do маркеры
        clean_preview = re.sub(r'-\s*\[\s*[xX\s]?\s*\]\s*', '', clean_preview)
        
        clean_preview = clean_preview.strip()
        if len(clean_preview) > 120:
            preview_text = clean_preview[:120].strip() + "..."
        else:
            preview_text = clean_preview
            
        final_report_text = f"✅ *Заметка создана!*\n\n📋 *{notion_title}*\n_{preview_text}_"
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
        
        if created_events_links and created_events_links[0]:
            action_buttons.append([
                {"text": "📅 Открыть в календаре", "url": created_events_links[0]}
            ])
        
        if status_message_id:
            edit_telegram_message(chat_id, status_message_id, final_report_text, inline_buttons=action_buttons)
        else:
            send_message_with_buttons(chat_id, final_report_text, action_buttons)
