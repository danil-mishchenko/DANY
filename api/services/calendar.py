# -*- coding: utf-8 -*-
"""Сервис для работы с Google Calendar."""
import json
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

from utils.config import GOOGLE_CREDENTIALS_JSON, GOOGLE_CALENDAR_ID, USER_TIMEZONE
from utils.markdown import markdown_to_gcal_html


def create_google_calendar_event(title: str, description: str, start_time_iso: str):
    """Создает событие в Google Календаре, конвертируя описание в HTML."""
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
    return created_event.get('id')


def delete_gcal_event(calendar_id: str, event_id: str):
    """Удаляет событие из Google Календаря."""
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        service = build('calendar', 'v3', credentials=creds)
        
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"Событие GCal {event_id} удалено.")
        return True
    except Exception as e:
        print(f"Ошибка при удалении события GCal: {e}")
        return False
