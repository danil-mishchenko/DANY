# -*- coding: utf-8 -*-
"""Command Handler for Telegram Bot."""

import os
import requests as req

from services.telegram import (
    send_telegram_message,
    send_message_with_buttons
)
from services.notion import (
    get_latest_notes,
    get_notion_page_content,
    get_page_title,
    get_page_preview,
    search_notion_pages
)
from services.pinecone_svc import (
    upsert_parent_child_chunks,
    query_pinecone_parent_child,
    apply_temporal_decay,
    delete_from_pinecone,
    clear_pinecone_index
)
from services.state import (
    get_last_created_page_id,
    set_user_state,
    get_hidden_tasks,
    set_active_mode,
    get_transcript_clean,
    delete_note_content_cache,
    set_note_content_cache,
    set_note_metadata,
    get_note_metadata
)
from services.clickup import get_my_tasks, format_tasks_message
from services.briefing import build_morning_briefing, build_evening_briefing
from services.ai import summarize_for_search, expand_search_query
from services.calendar import get_calendar_events_for_range
from utils.ui import build_settings_message

def handle_command(chat_id: int, user_id: str, text: str, message: dict) -> bool:
    """Обработка текстовых команд бота.
    Возвращает True, если это была команда и она обработана.
    """
    if not text:
        return False
        
    text_clean = text.strip()
    
    # 1. /start
    if text_clean == '/start':
        send_telegram_message(
            chat_id, 
            "👋 *Привет!* Я твой бот для заметок.\n\n"
            "📝 Просто напиши или запиши голосовое — я создам заметку в Notion.\n\n"
            "Используй кнопки ниже для навигации:",
            show_keyboard=True
        )
        return True
        
    # 2. /help
    elif text_clean == '/help':
        help_msg = (
            "❓ *Доступные команды:*\n\n"
            "👋 /start — Начало работы и клавиатура\n"
            "📝 /notes — Последние 5 заметок в Notion\n"
            "🔍 /search <запрос> — Поиск по смыслу в заметках\n"
            "🧹 /reindex — Очистить и переиндексировать всё с нуля\n"
            "📋 /clickup — Показать задачи из ClickUp\n"
            "⏳ /briefing — Утренний брифинг\n"
            "⏳ /evening — Вечерний отчёт\n"
            "👁 /hide — Меню скрытия задач ClickUp\n"
            "↩️ /undo — Инструкция по отмене действий\n"
            "⚙️ /settings — Настройки уведомлений и транскрипта\n"
            "🎙 /transcript — Активировать режим транскрипта"
        )
        send_telegram_message(chat_id, help_msg, show_keyboard=True)
        return True

    # 3. /index_all или /reindex
    elif text_clean in ('/index_all', '/reindex'):
        is_reindex = text_clean == '/reindex'
        if is_reindex:
            send_telegram_message(chat_id, "🧹 Очищаю старый индекс поиска...")
            clear_pinecone_index()
            send_telegram_message(chat_id, "⏳ Начинаю полную переиндексацию с нуля. Это может занять время...")
        else:
            send_telegram_message(chat_id, "⏳ Начинаю обновление индексации заметок...")
            
        all_notes = get_latest_notes(100)
        indexed_count = 0
        for note in all_notes:
            page_id = note['id']
            try:
                if is_reindex:
                    delete_note_content_cache(page_id)
                    from services.state import delete_note_metadata
                    delete_note_metadata(page_id)
                    
                page_content = get_notion_page_content(page_id)
                title_parts = note.get('properties', {}).get('Name', {}).get('title', [])
                page_title = title_parts[0]['plain_text'] if title_parts else "Без названия"
                
                category_prop = note.get('properties', {}).get('Категория', {}).get('select')
                category = category_prop['name'] if category_prop else "Мысль"
                
                created_time = note.get('created_time', '')
                last_edited_time = note.get('last_edited_time', '')
                
                # Сохраняем в кэш контента и метаданных
                set_note_content_cache(page_id, page_content)
                meta = {
                    'title': page_title,
                    'category': category,
                    'created_time': created_time,
                    'last_edited_time': last_edited_time
                }
                set_note_metadata(page_id, meta)
                
                # Векторизуем чанками в Pinecone!
                upsert_parent_child_chunks(page_id, page_title, page_content)
                indexed_count += 1
            except Exception as e:
                print(f"Ошибка при индексации страницы {page_id}: {e}")
                
        send_telegram_message(chat_id, f"✅ Успешно! Проиндексировано {indexed_count} заметок.", show_keyboard=True)
        return True

    # 3.5. /clear_queue
    elif text_clean == '/clear_queue':
        send_telegram_message(chat_id, "🧹 Запрашиваю очистку очереди Telegram...")
        try:
            import requests
            from utils.config import TELEGRAM_TOKEN
            info_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo"
            info_res = requests.get(info_url, timeout=10).json()
            webhook_url = info_res.get('result', {}).get('url', '')
            
            if webhook_url:
                set_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true"
                res = requests.get(set_url, timeout=10).json()
                send_telegram_message(chat_id, f"🧹 *Очередь Telegram успешно очищена!*\n\nРезультат: `{res}`", show_keyboard=True)
            else:
                send_telegram_message(chat_id, "❌ Не удалось определить текущий URL вебхука.", show_keyboard=True)
        except Exception as clear_err:
            send_telegram_message(chat_id, f"❌ Ошибка при очистке очереди: `{clear_err}`", show_keyboard=True)
        return True
        
    # 4. /briefing
    elif text_clean == '/briefing':
        send_telegram_message(chat_id, "⏳ Собираю утренний брифинг...")
        try:
            briefing_msg = build_morning_briefing()
            send_telegram_message(chat_id, briefing_msg, use_html=True, show_keyboard=True)
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка брифинга: {e}", show_keyboard=True)
        return True
        
    # 5. /evening
    elif text_clean == '/evening':
        send_telegram_message(chat_id, "⏳ Собираю вечерний отчёт...")
        try:
            evening_msg = build_evening_briefing()
            send_telegram_message(chat_id, evening_msg, use_html=True, show_keyboard=True)
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка: {e}", show_keyboard=True)
        return True
        
    # 6. /hide
    elif text_clean == '/hide':
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
        return True
        

        
    # 8. /register_webhook
    elif text_clean == '/register_webhook':
        from utils.config import CLICKUP_API_TOKEN, CLICKUP_TEAM_ID
        vercel_url = os.environ.get('VERCEL_URL', '')
        if not vercel_url:
            send_telegram_message(chat_id, "❌ VERCEL_URL не установлен", show_keyboard=True)
            return True
            
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
        return True
        
    # 9. /notes or 📝 Заметки
    elif text_clean in ('/notes', '📝 Заметки'):
        send_telegram_message(chat_id, "🔎 Загружаю последние заметки...")
        latest_notes = get_latest_notes(5)
        if not latest_notes:
            send_telegram_message(chat_id, "😔 Заметок пока нет.", show_keyboard=True)
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
            
            send_message_with_buttons(chat_id, message_text, navigation_buttons)
        return True
        
    # 10. /search or 🔍 Поиск
    elif text_clean == '🔍 Поиск':
        set_user_state(user_id, 'awaiting_search', None)
        send_telegram_message(chat_id, "🔍 Введите поисковый запрос:")
        return True
        
    elif text_clean.startswith('/search '):
        query = text_clean.split(' ', 1)[1]
        if not query:
            send_telegram_message(chat_id, "Пожалуйста, укажите, что нужно найти после команды /search.")
            return True
            
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
            send_telegram_message(chat_id, "😔 Ничего не найдено по вашему запросу.")
            return True
            
        # 4. Собираем метаданные из Redis для временного затухания
        note_meta_dates = {}
        for match in matches_list:
            pid = match['id']
            meta = get_note_metadata(pid)
            if meta and meta.get('last_edited_time'):
                try:
                    from datetime import datetime
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
                from datetime import datetime, timezone, timedelta
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
        import re
        
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
                
        if not context:
            err_text = "\n".join(errors)
            send_telegram_message(chat_id, f"🤔 Нашел подходящие заметки, но не смог прочитать их содержимое.\n\n*Ошибки:*\n{err_text}")
            return True
            
        # 9. Генерация ответа ИИ
        answer = summarize_for_search(context, query)
        final_response = f"💡 <b>Вот что я нашел по вашему запросу:</b>\n\n{answer}"
        
        # Группируем кнопки-источники в ряды по 2 кнопки
        inline_buttons = []
        for i in range(0, len(source_buttons), 2):
            inline_buttons.append(source_buttons[i:i+2])
            
        send_message_with_buttons(chat_id, final_response, inline_buttons, use_html=True)
        return True

    elif text_clean.startswith('/debug_search '):
        query = text_clean.split(' ', 1)[1]
        if not query:
            send_telegram_message(chat_id, "Пожалуйста, укажите запрос.")
            return True
            
        send_telegram_message(chat_id, f"🔍 [DEBUG] Ищу по смыслу: '{query}'...")
        try:
            found_ids = query_pinecone(query, top_k=6)
            report = f"🔍 [DEBUG] Pinecone вернул {len(found_ids)} ID:\n`{found_ids}`\n\n"
        except Exception as pe:
            send_telegram_message(chat_id, f"❌ [DEBUG] Ошибка Pinecone: {pe}")
            return True
            
        if not found_ids:
            send_telegram_message(chat_id, report + "😔 Ничего не найдено.")
            return True
            
        for i, page_id in enumerate(found_ids):
            report += f"📄 *[{i+1}] ID: `{page_id}`*\n"
            try:
                title = get_page_title(page_id)
                report += f"• Название: `{title}`\n"
            except Exception as e:
                report += f"• Ошибка названия: `{e}`\n"
                
            try:
                content = get_notion_page_content(page_id)
                report += f"• Длина контента: `{len(content)}` симв.\n"
                report += f"• Превью: `{content[:100]}...`\n"
            except Exception as e:
                report += f"• Ошибка контента: `{e}`\n"
                if hasattr(e, 'response') and e.response is not None:
                    report += f"  - Status: `{e.response.status_code}`\n"
                    report += f"  - Body: `{e.response.text[:200]}`\n"
            report += "\n"
            
        send_telegram_message(chat_id, report)
        return True
        
    # 11. /undo
    elif text_clean == '/undo':
        send_telegram_message(chat_id, "Пожалуйста, используйте кнопку '↩️ Отменить' под сообщением.")
        return True
        
    # 12. /edit
    elif text_clean.startswith('/edit'):
        edit_text = text_clean[5:].strip()
        
        if not edit_text:
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
            return True
            
        last_page_id = get_last_created_page_id()
        if not last_page_id:
            send_telegram_message(
                chat_id, 
                "❌ Не удалось найти последнюю заметку.\n\n"
                "Возможно, лог действий пуст или не настроен."
            )
            return True
            
        page_title = get_page_title(last_page_id)
        set_user_state(user_id, 'pending_edit', last_page_id, edit_text)
        
        buttons = [[
            {"text": "➕ Просто добавить", "callback_data": f"edit_simple_{last_page_id}"},
            {"text": "✨ Добавить + Полировка", "callback_data": f"edit_polish_{last_page_id}"}
        ]]
        
        msg = f"📝 Добавить в *{page_title}*:\n\n_{edit_text}_"
        send_message_with_buttons(chat_id, msg, buttons)
        return True
        
    # 13. 📋 ClickUp / /clickup
    elif text_clean in ('📋 ClickUp', '/clickup'):
        hidden_ids = get_hidden_tasks(user_id)
        tasks = get_my_tasks()
        msg = format_tasks_message(tasks, hidden_ids=hidden_ids)
        
        buttons = [[{"text": "🔄 Обновить", "callback_data": "clickup_refresh"}]]
        if hidden_ids:
            buttons.append([{"text": f"👁 Показать скрытые ({len(hidden_ids)})", "callback_data": "unhide_all"}])
        buttons.append([{"text": "🌐 Открыть ClickUp", "url": "https://app.clickup.com"}])
        
        send_message_with_buttons(chat_id, msg, buttons)
        return True
        
    # 14. 🎙 Транскрипт / /transcript
    elif text_clean in ('🎙 Транскрипт', '/transcript'):
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
        return True
        
    # 15. ⚙️ Настройки / /settings
    elif text_clean in ('⚙️ Настройки', '/settings'):
        msg, buttons = build_settings_message(user_id)
        send_message_with_buttons(chat_id, msg, buttons)
        return True
        
    # 16. /today
    elif text_clean == '/today':
        # Перенаправляем на утренний брифинг
        send_telegram_message(chat_id, "⏳ Собираю сегодняшний брифинг...")
        try:
            briefing_msg = build_morning_briefing()
            send_telegram_message(chat_id, briefing_msg, use_html=True, show_keyboard=True)
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка брифинга: {e}", show_keyboard=True)
        return True
        
    # 17. /cron
    elif text_clean == '/cron':
        send_telegram_message(chat_id, "⏰ Cron-задачи активны и автоматически запускаются сервером по расписанию.")
        return True
        
    return False
