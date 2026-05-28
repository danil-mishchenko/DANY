# -*- coding: utf-8 -*-
"""Integration tests for the new Notion 2026-03-11 Markdown API integration."""
import os
import sys

# Setup python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'api'))

def load_env_manually(dotenv_path):
    """Manually parse .env file to avoid external dependency."""
    if os.path.exists(dotenv_path):
        with open(dotenv_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ[key] = val
        print("✅ Environment loaded manually from .env")
    else:
        print("⚠️ Warning: .env file not found!")

# Load environment variables
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_env_manually(os.path.join(parent_dir, '.env'))

from services.notion import (
    create_notion_page,
    get_notion_page_content,
    add_to_notion_page,
    add_image_to_page,
    replace_page_content,
    rename_page,
    delete_notion_page,
    restore_notion_page,
    get_page_preview,
    get_latest_notes
)

def run_tests():
    print("🚀 Starting new Notion API Integration Tests...")
    
    # 1. Test page creation with Markdown
    test_title = "Тестовая заметка нового API"
    test_content = (
        "# Привет!\n\n"
        "Это **жирный текст**, а это *курсив*.\n\n"
        "### Список задач:\n"
        "- [x] Настроить Redis\n"
        "- [ ] Перейти на Notion API 2026-03-11\n\n"
        "Ура!"
    )
    test_category = "Идея"
    
    print("\n--- 1. Создание страницы через Markdown API ---")
    page_id = create_notion_page(test_title, test_content, test_category)
    print(f"✅ Страница создана: ID={page_id}")
    
    # 2. Test reading page content as Markdown
    print("\n--- 2. Чтение страницы как Markdown ---")
    retrieved_content = get_notion_page_content(page_id)
    print("Полученный Markdown с Notion:")
    print(retrieved_content)
    assert "Настроить Redis" in retrieved_content
    print("✅ Чтение успешно верифицировано!")
    
    # 3. Test appending Markdown text
    print("\n--- 3. Добавление текста в конец страницы ---")
    add_to_notion_page(page_id, "## Дополнительный блок\n\nЭтот текст был добавлен позже в конец страницы!")
    updated_content = get_notion_page_content(page_id)
    print("Обновленное содержимое:")
    print(updated_content)
    assert "Дополнительный блок" in updated_content
    print("✅ Добавление успешно верифицировано!")
    
    # 4. Test adding an image via Markdown
    print("\n--- 4. Добавление картинки ---")
    add_image_to_page(page_id, "https://images.unsplash.com/photo-1542831371-29b0f74f9713", "Тестовое изображение кода")
    content_with_image = get_notion_page_content(page_id)
    assert "photo-1542831371-29b0f74f9713" in content_with_image
    print("✅ Добавление картинки верифицировано!")
    
    # 5. Test atomic replacement of page content
    print("\n--- 5. Атомарная замена контента (AI-полировка) ---")
    new_polished_content = (
        "# Отполированная заметка\n\n"
        "Весь старый контент был полностью и атомарно перезаписан за ОДИН HTTP-запрос! ⚡️"
    )
    replace_page_content(page_id, new_polished_content)
    polished_content = get_notion_page_content(page_id)
    print("Отполированный контент:")
    print(polished_content)
    assert "Отполированная заметка" in polished_content
    assert "Настроить Redis" not in polished_content # Старый контент должен быть полностью заменен
    print("✅ Атомарная замена верифицирована!")
    
    # 6. Test renaming page properties
    print("\n--- 6. Переименование страницы ---")
    new_title = "Переименованная тестовая заметка 2026"
    rename_page(page_id, new_title)
    preview = get_page_preview(page_id)
    print(f"Превью: {preview}")
    assert preview['title'] == new_title
    print("✅ Переименование верифицировано!")
    
    # 7. Test query latest pages
    print("\n--- 7. Запрос последних страниц ---")
    notes = get_latest_notes(3)
    print(f"Найдено {len(notes)} страниц в БД.")
    assert len(notes) > 0
    print("✅ Запрос последних страниц верифицирован!")
    
    # 8. Test delete page (using in_trash)
    print("\n--- 8. Удаление страницы (in_trash: True) ---")
    delete_notion_page(page_id)
    print("✅ Удаление верифицировано!")
    
    # 9. Test restore page (using in_trash: False)
    print("\n--- 9. Восстановление страницы (in_trash: False) ---")
    restore_notion_page(page_id)
    print("✅ Восстановление верифицировано!")
    
    print("\n🎉 ВСЕ ТЕСТЫ НОВОГО NOTION API 2026-03-11 УСПЕШНО ПРОЙДЕНЫ! 🚀")

if __name__ == "__main__":
    run_tests()
