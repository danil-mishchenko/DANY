# -*- coding: utf-8 -*-
"""Сервис для работы с Google Calendar."""
import json
from datetime import datetime, timedelta

from utils.config import GOOGLE_CREDENTIALS_JSON, GOOGLE_CALENDAR_ID, USER_TIMEZONE
from utils.markdown import markdown_to_gcal_html


def create_google_calendar_event(title: str, description: str, start_time_iso: str):
    """Создает событие в Google Календаре, конвертируя описание в HTML.
    
    Returns:
        dict: {'id': event_id, 'html_link': URL для открытия события}
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(creds_info)
    service = build('calendar', 'v3', credentials=creds)
    start_time = datetime.fromisoformat(start_time_iso)
    end_time = start_time + timedelta(hours=1)
    
    html_description = markdown_to_gcal_html(description)

    event = {
        'summary': title,
        'description': html_description,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': USER_TIMEZONE},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': USER_TIMEZONE},
        'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 15}]}
    }
    created_event = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
    return {
        'id': created_event.get('id'),
        'html_link': created_event.get('htmlLink')
    }


def delete_gcal_event(calendar_id: str, event_id: str):
    """Удаляет событие из Google Календаря."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        service = build('calendar', 'v3', credentials=creds)
        
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"Событие GCal {event_id} удалено.")
        return True
    except Exception as e:
        print(f"Ошибка при удалении события GCal: {e}")
        return False


def get_calendar_events_for_range(start_time_iso: str, end_time_iso: str) -> list:
    """Получает события из Google Календаря за указанный промежуток времени.
    
    start_time_iso: ISO строка (например, '2026-05-30T00:00:00+03:00')
    end_time_iso: ISO строка (например, '2026-05-31T23:59:59+03:00')
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        service = build('calendar', 'v3', credentials=creds)
        
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start_time_iso,
            timeMax=end_time_iso,
            singleEvents=True,
            orderBy='startTime',
            maxResults=25
        ).execute()
        
        events = events_result.get('items', [])
        formatted_events = []
        for event in events:
            start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
            end = event.get('end', {}).get('dateTime') or event.get('end', {}).get('date')
            formatted_events.append({
                'summary': event.get('summary', 'Без названия'),
                'description': event.get('description', ''),
                'start': start,
                'end': end,
                'link': event.get('htmlLink', '')
            })
        print(f"[calendar.py] Успешно загружено {len(formatted_events)} событий из Google Calendar.")
        return formatted_events
    except Exception as e:
        print(f"[calendar.py] Ошибка при чтении календаря: {e}")
        return []

