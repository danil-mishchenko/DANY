# -*- coding: utf-8 -*-
"""Утилиты для работы с форматированием текста."""
import re

def markdown_to_gcal_html(md_text: str) -> str:
    """Конвертирует простой Markdown в HTML для Google Календаря."""
    # Заменяем **жирный** на <b>жирный</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', md_text)
    # Заменяем *курсив* на <i>курсив</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    return text
