# -*- coding: utf-8 -*-
"""Message Handler for Telegram Bot."""

import re
from datetime import datetime

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
    rename_page
)
from services.calendar import create_google_calendar_event
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
    append_to_transcript_buffer
)
from services.ai import (
    transcribe_with_assemblyai,
    clean_transcript,
    process_with_ai,
    summarize_for_search
)
from services.pinecone_svc import query_pinecone

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


def handle_message(chat_id: int, user_id: str, text: str, message: dict):
    """Обработка обычных сообщений, состояний ожидания и медиафайлов."""
    
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
            query = message.get('text', '').strip()
            if query:
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
        send_telegram_message(chat_id, "⏳ Распознаю речь...")
        audio_bytes = download_telegram_file(audio_file_id).read()
        transcript_data = transcribe_with_assemblyai(audio_bytes)
        text_to_process = transcript_data.get('text') if transcript_data else None
        if not text_to_process: 
            send_telegram_message(chat_id, "❌ Не удалось распознать речь.")
            return
            
    elif 'text' in message:
        is_text_message = True
        text_to_process = message['text']

    # 6. Обработка извлеченного текста (Notion + Календарь)
    if text_to_process:
        status_message_id = None
        if is_text_message:
            status_message_id = send_initial_status_message(chat_id, "⏳ Записываю заметку...")
        
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
            notion_page_id = create_notion_page(notion_title, formatted_body, notion_category)
            if notion_page_id: 
                log_last_action(notion_page_id=notion_page_id)
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
            return

        created_events_titles = []
        created_events_links = []
        if valid_events:
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
        
        if created_events_links and created_events_links[0]:
            action_buttons.append([
                {"text": "📅 Открыть в календаре", "url": created_events_links[0]}
            ])
        
        if status_message_id:
            edit_telegram_message(chat_id, status_message_id, final_report_text, inline_buttons=action_buttons)
        else:
            send_message_with_buttons(chat_id, final_report_text, action_buttons)
