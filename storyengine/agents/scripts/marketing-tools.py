#!/usr/bin/env python3
"""
Marketing Strategist Tools
Helpers for Google Drive, Docs, competitor research, and lead list management.
Usage: python3 marketing-tools.py <command> [args]

Commands:
  create-workspace <name>          Create a Google Drive folder for a marketing project
  create-doc <folder_id> <title>   Create a Google Doc in the project folder
  upload-csv <folder_id> <path>    Upload a CSV (lead list, competitor data) to Drive
  list-files <folder_id>           List all files in a project folder
  competitor-scan <url>            Analyze a competitor's website
"""

import sys
import os
import json
import asyncio

# Add project root for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'skills', 'video-pipeline'))

from shared.clients.google_client import GoogleClient

# Google Drive base folder for marketing projects
MARKETING_DRIVE_FOLDER = os.getenv('MARKETING_DRIVE_FOLDER_ID', '1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD')


def create_workspace(name: str):
    """Create a new marketing project folder in Google Drive."""
    client = GoogleClient()
    folder = client.get_or_create_folder(name, parent_id=MARKETING_DRIVE_FOLDER)
    print(json.dumps({
        'folder_id': folder['id'],
        'folder_name': name,
        'url': f"https://drive.google.com/drive/folders/{folder['id']}"
    }, indent=2))
    return folder


def create_doc(folder_id: str, title: str, content: str = ''):
    """Create a Google Doc in the project folder."""
    client = GoogleClient()
    doc = client.create_document(title, folder_id=folder_id)
    doc_id = doc.get('documentId', doc.get('id', ''))

    # If content provided, write it
    if content and doc_id:
        try:
            requests = [{'insertText': {'location': {'index': 1}, 'text': content}}]
            client.docs_service.documents().batchUpdate(
                documentId=doc_id, body={'requests': requests}
            ).execute()
        except Exception as e:
            print(f"Warning: Could not write content: {e}", file=sys.stderr)

    print(json.dumps({
        'doc_id': doc_id,
        'title': title,
        'url': f"https://docs.google.com/document/d/{doc_id}/edit"
    }, indent=2))
    return doc


def upload_csv(folder_id: str, file_path: str):
    """Upload a CSV file to the project folder."""
    client = GoogleClient()
    name = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        content = f.read()
    result = client.upload_file(
        content=content,
        name=name,
        folder_id=folder_id,
        mime_type='text/csv'
    )
    file_id = result.get('id', '')
    print(json.dumps({
        'file_id': file_id,
        'name': name,
        'url': f"https://drive.google.com/file/d/{file_id}/view"
    }, indent=2))
    return result


def list_files(folder_id: str):
    """List all files in a project folder."""
    client = GoogleClient()
    files = client.list_files_in_folder(folder_id)
    for f in files:
        print(f"  {f.get('name', '?')} — https://drive.google.com/file/d/{f.get('id', '')}/view")
    if not files:
        print("  (empty folder)")
    return files


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'create-workspace':
        create_workspace(sys.argv[2])
    elif cmd == 'create-doc':
        content = sys.argv[4] if len(sys.argv) > 4 else ''
        create_doc(sys.argv[2], sys.argv[3], content)
    elif cmd == 'upload-csv':
        upload_csv(sys.argv[2], sys.argv[3])
    elif cmd == 'list-files':
        list_files(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
