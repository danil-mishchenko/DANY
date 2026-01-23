# -*- coding: utf-8 -*-
"""Утилиты для работы с Markdown и форматированием."""
import re


def markdown_to_gcal_html(md_text: str) -> str:
    """Конвертирует простой Markdown в HTML для Google Календаря."""
    # Заменяем **жирный** на <b>жирный</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', md_text)
    # Заменяем *курсив* на <i>курсив</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    return text


def parse_to_notion_blocks(formatted_text: str) -> list:
    """
    Превращает текст в нативные блоки Notion, корректно находя URL в любой части строки
    и используя остальной текст как подпись к закладке.
    """
    blocks = []
    url_pattern = re.compile(r'https?://\S+')

    for line in formatted_text.split('\n'):
        stripped_line = line.strip()
        if not stripped_line:
            continue

        # 1. Ищем URL в строке
        match = url_pattern.search(stripped_line)
        
        if match:
            url = match.group(0)
            caption_text = url_pattern.sub('', stripped_line).strip(' -').strip()
            
            bookmark_block = {
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": url}
            }
            if caption_text:
                bookmark_block["bookmark"]["caption"] = [{"type": "text", "text": {"content": caption_text}}]

            blocks.append(bookmark_block)
            continue

        # 2. Обрабатываем как обычный текст
        is_bullet_item = stripped_line.startswith('- ')
        block_type = "bulleted_list_item" if is_bullet_item else "paragraph"
        clean_line = stripped_line.lstrip('- ') if is_bullet_item else stripped_line
        
        # Парсим inline-форматирование
        rich_text_objects = []
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*)', clean_line)
        for part in filter(None, parts):
            is_bold = part.startswith('**') and part.endswith('**')
            is_italic = part.startswith('*') and part.endswith('*')
            content = part.strip('**').strip('*')
            annotations = {"bold": is_bold, "italic": is_italic}
            rich_text_objects.append({"type": "text", "text": {"content": content}, "annotations": annotations})

        if rich_text_objects:
            if block_type == "bulleted_list_item":
                blocks.append({"object": "block", "type": block_type, "bulleted_list_item": {"rich_text": rich_text_objects}})
            else:
                blocks.append({"object": "block", "type": block_type, "paragraph": {"rich_text": rich_text_objects}})
            
    return blocks
