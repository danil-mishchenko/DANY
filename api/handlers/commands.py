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
    get_page_preview
)
from services.pinecone_svc import (
    upsert_to_pinecone,
    query_pinecone
)
from services.state import (
    get_last_created_page_id,
    set_user_state,
    get_hidden_tasks,
    set_active_mode,
    get_transcript_clean
)
from services.clickup import get_my_tasks, format_tasks_message
from services.briefing import build_morning_briefing, build_evening_briefing
from services.ai import summarize_for_search
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

    # 3. /index_all
    elif text_clean == '/index_all':
        send_telegram_message(chat_id, "Начинаю полную индексацию всех заметок. Это может занять время...")
        all_notes = get_latest_notes(100)
        for note in all_notes:
            page_id = note['id']
            page_content = get_notion_page_content(page_id)
            upsert_to_pinecone(page_id, page_content)
        send_telegram_message(chat_id, f"✅ Готово! Проиндексировано {len(all_notes)} заметок.", show_keyboard=True)
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
        found_ids = query_pinecone(query, top_k=6)
        
        if not found_ids:
            send_telegram_message(chat_id, "😔 Ничего не найдено по вашему запросу.")
            return True

        context = ""
        for page_id in found_ids:
            try:
                page_content = get_notion_page_content(page_id)
                page_title = page_content.split('\n', 1)[0] if page_content else "Без названия"
                context += f"--- Текст из заметки '{page_title}' ---\n{page_content}\n\n"
            except Exception as e:
                print(f"Не удалось получить контент для страницы {page_id}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    if getattr(e.response, 'status_code', None) in (400, 403, 404):
                        try:
                            from services.pinecone_svc import delete_from_pinecone
                            delete_from_pinecone(page_id)
                        except Exception as pe:
                            print(f"Не удалось очистить Pinecone для {page_id}: {pe}")

        if not context:
            send_telegram_message(chat_id, "🤔 Нашел подходящие заметки, но не смог прочитать их содержимое.")
            return True

        answer = summarize_for_search(context, query)
        final_response = f"💡 *Вот что я нашел по вашему запросу:*\n\n{answer}"
        send_telegram_message(chat_id, final_response)
        return True

    elif text_clean.startswith('/debug_search '):
        query = text_clean.split(' ', 1)[1]
        if not query:
            send_telegram_message(chat_id, "Пожалуйста, укажите запрос.")
            return True
            
        send_telegram_message(chat_id, f"🔍 [DEBUG] Ищу по смыслу: '{query}'...")
        try:
            from services.pinecone_svc import query_pinecone
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
