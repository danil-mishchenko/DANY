# -*- coding: utf-8 -*-
"""Service for exporting Notion notes to Markdown."""
import requests
import time
from datetime import datetime
from api.utils.config import NOTION_TOKEN, NOTION_DATABASE_ID, DEFAULT_TIMEOUT
from api.services.notion import get_notion_page_content

def fetch_all_pages():
    """Fetches all pages from the Notion database with pagination."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28'
    }
    
    all_pages = []
    has_more = True
    next_cursor = None
    
    print(f"Starting export from database: {NOTION_DATABASE_ID}")
    
    while has_more:
        payload = {"page_size": 100}
        if next_cursor:
            payload["start_cursor"] = next_cursor
            
        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        results = data.get('results', [])
        all_pages.extend(results)
        
        has_more = data.get('has_more', False)
        next_cursor = data.get('next_cursor')
        
        print(f"Fetched {len(results)} pages... Total: {len(all_pages)}")
        
        if has_more:
            time.sleep(0.5)  # Respect rate limits
            
    return all_pages

def format_note_as_markdown(page):
    """Formats a single Notion page as a Markdown block."""
    properties = page.get('properties', {})
    
    # 1. Get Title
    title = "Untitled"
    title_prop = properties.get('Name', {}).get('title', [])
    if title_prop:
        title = title_prop[0].get('plain_text', 'Untitled')
        
    # 2. Get Category
    category = "Uncategorized"
    cat_prop = properties.get('Категория', {}).get('select')
    if cat_prop:
        category = cat_prop.get('name', 'Uncategorized')
        
    # 3. Get Creation Date
    created_time_str = page.get('created_time', '')
    if created_time_str:
        # Format: 2024-04-20T04:45:17.000Z -> 2024-04-20
        date_obj = datetime.fromisoformat(created_time_str.replace('Z', '+00:00'))
        date_str = date_obj.strftime('%Y-%m-%d %H:%M')
    else:
        date_str = "Unknown Date"
        
    # 4. Get Full Content
    page_id = page['id']
    try:
        content = get_notion_page_content(page_id)
    except Exception as e:
        content = f"*Error fetching content: {e}*"
        
    # 5. Build Markdown
    md = []
    md.append(f"# {title}")
    md.append(f"**Category:** {category} | **Created:** {date_str}")
    md.append(f"\n{content}")
    md.append("\n---\n")
    
    return "\n".join(md)

def export_to_file(output_path="notes_export.md"):
    """Main function to perform the export."""
    pages = fetch_all_pages()
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"--- EXPORTED ON {datetime.now().strftime('%Y-%m-%d %H:%M')} ---\n\n")
        
        for i, page in enumerate(pages):
            print(f"Processing ({i+1}/{len(pages)}): {page['id']}...")
            note_md = format_note_as_markdown(page)
            f.write(note_md)
            f.write("\n")
            
    print(f"\nSUCCESS: Exported {len(pages)} notes to {output_path}")
    return output_path
