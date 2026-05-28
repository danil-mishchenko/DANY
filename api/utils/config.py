# -*- coding: utf-8 -*-
"""Конфигурация и переменные окружения."""
import os

# --- Константы для надежности ---
DEFAULT_TIMEOUT = (5, 30)  # (connect_timeout, read_timeout) в секундах
MAX_POLLING_ATTEMPTS = 60  # Максимум попыток опроса (2 минуты при 2 сек паузе)
USER_TIMEZONE = os.getenv('USER_TIMEZONE', 'Europe/Kyiv')

# --- Валидация переменных окружения ---
REQUIRED_ENV_VARS = [
    'TELEGRAM_TOKEN', 'NOTION_TOKEN', 'NOTION_DATABASE_ID',
    'OPENAI_API_KEY', 'PINECONE_API_KEY', 'PINECONE_HOST'
]

def validate_env_vars():
    """Проверяет наличие обязательных переменных окружения."""
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {missing}")

# --- Секретные ключи и ID ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
NOTION_LOG_DB_ID = os.getenv('NOTION_LOG_DB_ID')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')
GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')
ALLOWED_TELEGRAM_ID = os.getenv('ALLOWED_TELEGRAM_ID')
ASSEMBLYAI_API_KEY = os.getenv('ASSEMBLYAI_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
PINECONE_HOST = os.getenv('PINECONE_HOST')
CLICKUP_API_TOKEN = os.getenv('CLICKUP_API_TOKEN')
CLICKUP_TEAM_ID = os.getenv('CLICKUP_TEAM_ID', '24387826')
CLICKUP_USER_ID = os.getenv('CLICKUP_USER_ID', '93710556')

# --- Маппинг категорий ---
CATEGORY_EMOJI_MAP = {
    "Задача": "✅",
    "Встреча": "🤝",
    "Идея": "💡",
    "Покупка": "🛒",
    "Мысль": "🤔",
    "Ссылка": "🔗",
    "Цитата": "💬",
    "Быстрая заметка": "📄"
}
