# -*- coding: utf-8 -*-
"""UI Helpers for Telegram Bot."""

from services.state import (
    get_user_settings,
    get_transcript_clean,
    get_transcript_single_mode
)

def build_settings_message(user_id: str) -> tuple[str, list[list[dict]]]:
    """Генерирует текст и инлайн-клавиатуру для меню настроек."""
    settings = get_user_settings(user_id)
    current_minutes = settings.get('reminder_minutes', 15)
    is_clean = get_transcript_clean(user_id)
    is_single = get_transcript_single_mode(user_id)
    
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
            {"text": "💬 Одиночный" + (" ✓" if is_single else ""), "callback_data": "set_transcript_single_mode"},
            {"text": "💬💬 Поток" + (" ✓" if not is_single else ""), "callback_data": "set_transcript_multi_mode"}
        ],
        [
            {"text": "📜 Дословный" + (" ✓" if not is_clean else ""), "callback_data": "set_transcript_raw"},
            {"text": "✨ Чистый" + (" ✓" if is_clean else ""), "callback_data": "set_transcript_clean"}
        ]
    ]
    
    clean_desc = "✨ Чистый — без слов-заполнителей" if is_clean else "📜 Дословный — точная цитата"
    mode_desc = "⚡️ Одиночный (с таймкодами)" if is_single else "🔄 Поток (склеивает несколько аудио)"
    msg = f"⚙️ *Настройки*\n\n📱 *Уведомления*\nЗа сколько минут до события?\n_Текущее: {current_minutes} мин_\n\n🎙 *Транскрипт*\nМетод обработки: _{mode_desc}_\nПодрежим расшифровки: _{clean_desc}_"
    
    return msg, buttons
