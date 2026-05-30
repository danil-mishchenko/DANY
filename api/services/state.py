# -*- coding: utf-8 -*-
"""Upstash Redis State Management Service.

Provides API compatible with notion.py state/settings storage, using Upstash Redis.
Includes module-level in-memory cache for user settings to optimize latency.
"""
import os
import json
import uuid
import sys
from datetime import datetime
from typing import Union, Optional, List, Dict, Any

# Global in-memory cache for user settings
# Key: user_id (str), Value: dict of settings
_settings_cache: Dict[str, Dict[str, Any]] = {}

UPSTASH_REDIS_REST_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')

# Default user settings matching the notion.py schema
DEFAULT_SETTINGS = {
    'reminder_minutes': 15,
    'hidden_tasks': [],
    'active_mode': 'note',
    'transcript_clean': False,
    'transcript_single_mode': False
}





class InMemoryRedis:
    """In-memory Redis Mock fallback.
    
    Used when Upstash Redis credentials are not provided or connection fails,
    ensuring the system remains completely operational.
    """
    def __init__(self):
        self.store = {}
        print("[state.py] Fallback InMemoryRedis initialized.")

    def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None) -> str:
        self.store[key] = str(value)
        return "OK"

    def setex(self, key: str, seconds: int, value: str) -> str:
        self.store[key] = str(value)
        return "OK"

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                count += 1
        return count

    def lpush(self, key: str, *values: str) -> int:
        if key not in self.store:
            self.store[key] = []
        if not isinstance(self.store[key], list):
            self.store[key] = [self.store[key]]
        for val in reversed(values):
            self.store[key].insert(0, str(val))
        return len(self.store[key])

    def rpush(self, key: str, *values: str) -> int:
        if key not in self.store:
            self.store[key] = []
        if not isinstance(self.store[key], list):
            self.store[key] = [self.store[key]]
        for val in values:
            self.store[key].append(str(val))
        return len(self.store[key])

    def lpop(self, key: str) -> Optional[str]:
        if key in self.store and isinstance(self.store[key], list) and self.store[key]:
            return self.store[key].pop(0)
        return None

    def lrange(self, key: str, start: int, stop: int) -> List[str]:
        if key in self.store and isinstance(self.store[key], list):
            lst = self.store[key]
            end = len(lst) if stop == -1 else stop + 1
            return lst[start:end]
        return []


# Initialize client
redis_client = None
if UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN:
    try:
        from upstash_redis import Redis
        redis_client = Redis(url=UPSTASH_REDIS_REST_URL, token=UPSTASH_REDIS_REST_TOKEN)
        print("[state.py] Connected to Upstash Redis REST API successfully.")
    except Exception as e:
        print(f"[state.py] Error initializing Upstash Redis: {e}. Falling back to In-Memory.")
        redis_client = InMemoryRedis()
else:
    print("[state.py] Warning: Redis credentials not found in env. Falling back to In-Memory.")
    redis_client = InMemoryRedis()


# === 1. USER STATE MANAGEMENT ===

def get_user_state(user_id: str) -> Optional[dict]:
    """Checks if there is an active state for the user, returns it and deletes it.
    
    Compatible with notion.py's implementation.
    """
    user_id = str(user_id)
    key = f"dany:user:{user_id}:state"
    try:
        data = redis_client.get(key)
        if data:
            redis_client.delete(key)
            return json.loads(data)
    except Exception as e:
        print(f"[state.py] Error fetching user state: {e}")
    return None


def set_user_state(user_id: str, state: Optional[str], page_id: Optional[str] = None, pending_edit_text: Optional[str] = None):
    """Saves user state with metadata, or clears it if state is None."""
    user_id = str(user_id)
    key = f"dany:user:{user_id}:state"
    
    if state is None:
        try:
            redis_client.delete(key)
        except Exception as e:
            print(f"[state.py] Error deleting user state: {e}")
    else:
        state_data = {
            'state': state,
            'page_id': page_id,
            'pending_edit_text': pending_edit_text
        }
        try:
            redis_client.set(key, json.dumps(state_data, ensure_ascii=False))
        except Exception as e:
            print(f"[state.py] Error setting user state: {e}")


# === 2. ACTIVE MODE ===

def get_active_mode(user_id: str) -> str:
    """Returns bot's active mode for the user, defaults to "note"."""
    settings = get_user_settings(user_id)
    return settings.get('active_mode') or "note"


def set_active_mode(user_id: str, mode: Optional[str]):
    """Saves active mode for the user."""
    settings = get_user_settings(user_id)
    settings['active_mode'] = mode
    set_user_settings(user_id, settings)


# === 3. TRANSCRIPT SETTINGS ===

def get_transcript_clean(user_id: str) -> bool:
    """Returns True if clean transcript mode is enabled."""
    settings = get_user_settings(user_id)
    return settings.get('transcript_clean', False)


def set_transcript_clean(user_id: str, is_clean: bool):
    """Sets clean transcript mode option."""
    settings = get_user_settings(user_id)
    settings['transcript_clean'] = is_clean
    set_user_settings(user_id, settings)


def get_transcript_single_mode(user_id: str) -> bool:
    """Returns True if single transcript mode is enabled."""
    settings = get_user_settings(user_id)
    return settings.get('transcript_single_mode', False)


def set_transcript_single_mode(user_id: str, is_single: bool):
    """Sets single transcript mode option."""
    settings = get_user_settings(user_id)
    settings['transcript_single_mode'] = is_single
    set_user_settings(user_id, settings)


# === 4. CLICKUP HIDDEN TASKS ===

def get_hidden_tasks(user_id: str) -> List[str]:
    """Returns the list of ClickUp task IDs that are hidden."""
    settings = get_user_settings(user_id)
    return settings.get('hidden_tasks', [])


def set_hidden_tasks(user_id: str, task_ids: List[str]):
    """Saves the list of hidden ClickUp task IDs."""
    settings = get_user_settings(user_id)
    settings['hidden_tasks'] = task_ids
    set_user_settings(user_id, settings)


def add_hidden_task(user_id: str, task_id: str):
    """Appends task ID to user's hidden tasks list."""
    settings = get_user_settings(user_id)
    hidden = settings.get('hidden_tasks', [])
    if task_id not in hidden:
        hidden.append(task_id)
        settings['hidden_tasks'] = hidden
        set_user_settings(user_id, settings)


def clear_hidden_tasks(user_id: str):
    """Clears user's hidden tasks list."""
    settings = get_user_settings(user_id)
    settings['hidden_tasks'] = []
    set_user_settings(user_id, settings)


# === 5. UNIFIED SETTINGS (WITH CACHE) ===

def get_user_settings(user_id: str) -> dict:
    """Fetches all user settings in one dictionary, utilizing in-memory cache."""
    user_id = str(user_id)
    if user_id in _settings_cache:
        return _settings_cache[user_id]
    
    key = f"dany:user:{user_id}:settings"
    try:
        data = redis_client.get(key)
        if data:
            settings = json.loads(data)
            full_settings = DEFAULT_SETTINGS.copy()
            full_settings.update(settings)
            _settings_cache[user_id] = full_settings
            return full_settings
    except Exception as e:
        print(f"[state.py] Error reading settings from Redis for {user_id}: {e}")
        
    default_copy = DEFAULT_SETTINGS.copy()
    _settings_cache[user_id] = default_copy
    return default_copy


def set_user_settings(user_id: str, settings_dict: Union[dict, int]):
    """Saves user settings to Redis and updates the local in-memory cache.
    
    Supports dictionary updates and integer (reminder_minutes) updates.
    """
    user_id = str(user_id)
    current_settings = get_user_settings(user_id)
    
    if isinstance(settings_dict, dict):
        current_settings.update(settings_dict)
    elif isinstance(settings_dict, int):
        current_settings['reminder_minutes'] = settings_dict
        
    _settings_cache[user_id] = current_settings
    
    key = f"dany:user:{user_id}:settings"
    try:
        redis_client.set(key, json.dumps(current_settings, ensure_ascii=False))
    except Exception as e:
        print(f"[state.py] Error writing settings to Redis for {user_id}: {e}")





# === 7. TEMP TRANSCRIPTS ===

def save_temp_transcript(user_id: str, transcript: str) -> str:
    """Saves transcript string temporarily with a TTL of 24h and returns its key ID."""
    log_id = uuid.uuid4().hex
    key = f"dany:temp_transcript:{log_id}"
    try:
        redis_client.setex(key, 86400, transcript)
    except Exception as e:
        print(f"[state.py] Error saving temp transcript: {e}")
    return log_id


def get_temp_transcript(log_id: str) -> Optional[str]:
    """Retrieves temporary transcript and deletes it instantly."""
    key = f"dany:temp_transcript:{log_id}"
    try:
        content = redis_client.get(key)
        if content:
            redis_client.delete(key)
            return content
    except Exception as e:
        print(f"[state.py] Error fetching temp transcript: {e}")
    return None


# === 8. MULTI-TRANSCRIPT BUFFER ===

def get_transcript_buffer(user_id: str) -> tuple:
    """Returns tuple of (buffer_id, content_string) of the accumulated transcript."""
    user_id = str(user_id)
    key = f"dany:user:{user_id}:transcript_buffer"
    try:
        items = redis_client.lrange(key, 0, -1)
        if items:
            return key, "\n\n---\n\n".join(items)
    except Exception as e:
        print(f"[state.py] Error fetching transcript buffer: {e}")
    return None, ""


def append_to_transcript_buffer(user_id: str, text: str) -> str:
    """Appends text segment to multi-transcript buffer and returns the entire buffer content."""
    user_id = str(user_id)
    key = f"dany:user:{user_id}:transcript_buffer"
    try:
        redis_client.rpush(key, text)
        _, content = get_transcript_buffer(user_id)
        return content
    except Exception as e:
        print(f"[state.py] Error appending to transcript buffer: {e}")
        return ""


def clear_transcript_buffer(user_id: str):
    """Deletes the multi-transcript buffer key."""
    user_id = str(user_id)
    key = f"dany:user:{user_id}:transcript_buffer"
    try:
        redis_client.delete(key)
    except Exception as e:
        print(f"[state.py] Error clearing transcript buffer: {e}")


# === 9. ACTION LOGGING ===

def log_last_action(user_id: str = None, action: str = None, page_id: str = None, notion_page_id: str = None, gcal_event_id: str = None, properties: dict = None, old_markdown: str = None):
    """Logs the last user action (Notion page or Calendar event).
    
    Compatible both with notion.py (taking properties) and new state API format.
    """
    # Simple fallback imports to avoid circular imports
    try:
        from utils.config import ALLOWED_TELEGRAM_ID, GOOGLE_CALENDAR_ID
        default_uid = ALLOWED_TELEGRAM_ID
        default_cal_id = GOOGLE_CALENDAR_ID
    except ImportError:
        default_uid = "default"
        default_cal_id = "primary"
        
    uid = str(user_id or default_uid or "default")
    key = f"dany:user:{uid}:action_log"
    
    action_data = {
        'notion_page_id': notion_page_id or page_id,
        'gcal_event_id': gcal_event_id,
        'gcal_calendar_id': default_cal_id or "primary",
        'action': action,
        'old_markdown': old_markdown,
        'timestamp': datetime.now().isoformat()
    }
    
    if properties:
        def get_text(prop):
            return prop['rich_text'][0]['text']['content'] if prop.get('rich_text') else None
        
        if 'NotionPageID' in properties:
            action_data['notion_page_id'] = get_text(properties['NotionPageID'])
        if 'GCalEventID' in properties:
            action_data['gcal_event_id'] = get_text(properties['GCalEventID'])
        if 'GCalCalendarID' in properties:
            action_data['gcal_calendar_id'] = get_text(properties['GCalCalendarID'])
            
    try:
        redis_client.lpush(key, json.dumps(action_data, ensure_ascii=False))
    except Exception as e:
        print(f"[state.py] Error logging last action: {e}")


def get_and_delete_last_log(user_id: str = None) -> Optional[dict]:
    """Fetches and deletes the last logged action (for undo functionality)."""
    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        default_uid = ALLOWED_TELEGRAM_ID
    except ImportError:
        default_uid = "default"
        
    uid = str(user_id or default_uid or "default")
    key = f"dany:user:{uid}:action_log"
    
    try:
        data = redis_client.lpop(key)
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"[state.py] Error fetching and deleting last action: {e}")
    return None


def get_last_created_page_id(user_id: str = None) -> Optional[str]:
    """Returns page ID of the last successfully created Notion page from action log."""
    try:
        from utils.config import ALLOWED_TELEGRAM_ID
        default_uid = ALLOWED_TELEGRAM_ID
    except ImportError:
        default_uid = "default"
        
    uid = str(user_id or default_uid or "default")
    key = f"dany:user:{uid}:action_log"
    
    try:
        # Search the last 20 actions for any valid Notion Page ID
        logs = redis_client.lrange(key, 0, 19)
        for log_str in logs:
            log_data = json.loads(log_str)
            page_id = log_data.get('notion_page_id')
            if page_id:
                return page_id
    except Exception as e:
        print(f"[state.py] Error fetching last page ID: {e}")
    return None


# === 10. NOTION NOTES CACHE ===

def get_notes_cache(user_id: str) -> Optional[list]:
    """Возвращает кэш последних заметок Notion для пользователя."""
    user_id = str(user_id)
    key = f"dany:user:{user_id}:notes_cache"
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"[state.py] Error fetching notes cache: {e}")
    return None


def set_notes_cache(user_id: str, notes: list):
    """Сохраняет последние заметки в кэш с TTL 1 час."""
    user_id = str(user_id)
    key = f"dany:user:{user_id}:notes_cache"
    try:
        redis_client.setex(key, 3600, json.dumps(notes, ensure_ascii=False))
    except Exception as e:
        print(f"[state.py] Error setting notes cache: {e}")


def invalidate_notes_cache(user_id: str):
    """Сбрасывает кэш заметок Notion для пользователя."""
    user_id = str(user_id)
    key = f"dany:user:{user_id}:notes_cache"
    try:
        redis_client.delete(key)
        print(f"[state.py] Notes cache invalidated for {user_id}")
    except Exception as e:
        print(f"[state.py] Error invalidating notes cache: {e}")
