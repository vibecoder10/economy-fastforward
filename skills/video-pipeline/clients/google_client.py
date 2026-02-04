"""Google Drive and Docs API client."""

import os
import io
from typing import Optional
import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


class GoogleClient:
    """Client for Google Drive and Docs APIs."""
    
    # Default folder ID from n8n workflow (Economy Fastforward folder)
    DEFAULT_PARENT_FOLDER_ID = "1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD"
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self.refresh_token = refresh_token or os.getenv("GOOGLE_REFRESH_TOKEN")
        
        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise ValueError("Google OAuth credentials not found in environment")
        
        self.parent_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", self.DEFAULT_PARENT_FOLDER_ID)
        
        # Initialize credentials
        self.credentials = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        
        # Initialize services
        self._drive_service = None
        self._docs_service = None
    
    @property
    def drive_service(self):
        """Get the Drive API service."""
        if self._drive_service is None:
            self._drive_service = build("drive", "v3", credentials=self.credentials)
        return self._drive_service
    
    @property
    def docs_service(self):
        """Get the Docs API service."""
        if self._docs_service is None:
            self._docs_service = build("docs", "v1", credentials=self.credentials)
        return self._docs_service
    
    # ==================== DRIVE OPERATIONS ====================
    
    def create_folder(self, name: str, parent_id: Optional[str] = None) -> dict:
        """Create a folder in Google Drive.
        
        Args:
            name: Folder name
            parent_id: Parent folder ID (uses default if not specified)
            
        Returns:
            Dict with folder id, name, and mimeType
        """
        parent = parent_id or self.parent_folder_id
        file_metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        
        folder = self.drive_service.files().create(
            body=file_metadata,
            fields="id, name, mimeType",
        ).execute()
        
        return folder
    
    def get_or_create_folder(self, name: str, parent_id: Optional[str] = None) -> dict:
        """Get existing folder or create new one.
        
        Args:
            name: Folder name
            parent_id: Parent folder ID (uses default if not specified)
            
        Returns:
            Dict with folder id, name, and mimeType
        """
        # First try to find existing folder
        existing = self.search_folder(name)
        if existing:
            return existing
        
        # Create new folder
        return self.create_folder(name, parent_id)
    
    def search_folder(self, name: str) -> Optional[dict]:
        """Search for a folder by name.
        
        Args:
            name: Folder name to search for
            
        Returns:
            Folder dict or None if not found
        """
        # Escape single quotes in folder name
        escaped_name = name.replace("'", "\\'")
        query = f"name = '{escaped_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        
        results = self.drive_service.files().list(
            q=query,
            fields="files(id, name, mimeType)",
        ).execute()
        
        files = results.get("files", [])
        return files[0] if files else None
    
    def search_folder_contains(self, name_part: str) -> Optional[dict]:
        """Search for a folder whose name contains the given string.
        
        Args:
            name_part: Partial folder name to search for
            
        Returns:
            First matching folder dict or None
        """
        escaped_name = name_part.replace("'", "\\'")
        query = f"name contains '{escaped_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        
        results = self.drive_service.files().list(
            q=query,
            fields="files(id, name, mimeType)",
        ).execute()
        
        files = results.get("files", [])
        return files[0] if files else None
    
    def search_file(self, name: str, folder_id: str) -> Optional[dict]:
        """Search for a file by name in a specific folder."""
        escaped_name = name.replace("'", "\\'")
        query = f"name = '{escaped_name}' and '{folder_id}' in parents and trashed = false"
        
        results = self.drive_service.files().list(
            q=query,
            fields="files(id, name, mimeType)",
        ).execute()
        
        files = results.get("files", [])
        return files[0] if files else None

    def upload_file(
        self,
        content: bytes,
        name: str,
        folder_id: str,
        mime_type: str = "audio/mpeg",
        check_existing: bool = True,
    ) -> dict:
        """Upload a file to Google Drive.
        
        Args:
            content: File content as bytes
            name: File name
            folder_id: Target folder ID
            mime_type: MIME type of the file
            check_existing: If True, checks if file exists and returns it instead of creating duplicate
            
        Returns:
            Dict with file id, name, and mimeType
        """
        if check_existing:
            existing_file = self.search_file(name, folder_id)
            if existing_file:
                print(f"      found existing file: {name} ({existing_file['id']})")
                return existing_file

        file_metadata = {
            "name": name,
            "parents": [folder_id],
        }
        
        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=mime_type,
            resumable=True,
        )
        
        file = self.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, mimeType",
        ).execute()
        
        return file
    
    def upload_image(self, content: bytes, name: str, folder_id: str) -> dict:
        """Upload an image to Google Drive."""
        return self.upload_file(content, name, folder_id, mime_type="image/png")
    
    def upload_audio(self, content: bytes, name: str, folder_id: str) -> dict:
        """Upload an audio file to Google Drive."""
        return self.upload_file(content, name, folder_id, mime_type="audio/mpeg")

    def upload_video(self, content: bytes, name: str, folder_id: str) -> dict:
        """Upload a video file to Google Drive."""
        return self.upload_file(content, name, folder_id, mime_type="video/mp4")

    def upload_file_from_url(
        self,
        url: str,
        name: str,
        parent_id: Optional[str] = None,
        mime_type: str = "image/png",
    ) -> dict:
        """Download a file from a URL and upload it to Google Drive.

        Args:
            url: URL to download the file from
            name: File name in Google Drive
            parent_id: Target folder ID (uses default if not specified)
            mime_type: MIME type of the file

        Returns:
            Dict with file id, name, mimeType, and webViewLink
        """
        response = httpx.get(url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()

        folder_id = parent_id or self.parent_folder_id
        file = self.upload_file(response.content, name, folder_id, mime_type=mime_type)

        # Make file publicly accessible
        self.make_file_public(file["id"])

        # Add webViewLink for Drive viewing
        file["webViewLink"] = f"https://drive.google.com/file/d/{file['id']}/view"
        return file

    def make_file_public(self, file_id: str) -> str:
        """Make a file public and return its direct download link (webContentLink)."""
        # 1. Add 'anyone' permission
        self.drive_service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
        ).execute()
        
        # 2. Get webContentLink
        file = self.drive_service.files().get(
            fileId=file_id,
            fields="webContentLink"
        ).execute()
        
        return file.get("webContentLink")
    
    # ==================== DOCS OPERATIONS ====================
    
    def create_document(self, title: str, folder_id: Optional[str] = None) -> dict:
        """Create a new Google Doc.
        
        Args:
            title: Document title
            folder_id: Folder to create doc in (if specified, doc will be moved there)
            
        Returns:
            Dict with document id and title
        """
        doc = self.docs_service.documents().create(
            body={"title": title}
        ).execute()
        
        doc_id = doc["documentId"]
        
        # Move to folder if specified
        if folder_id:
            self.drive_service.files().update(
                fileId=doc_id,
                addParents=folder_id,
                removeParents="root",
                fields="id, parents",
            ).execute()
        
        return {
            "id": doc_id,
            "title": title,
        }
    
    def append_to_document(self, doc_id: str, text: str) -> None:
        """Append text to a Google Doc.
        
        Args:
            doc_id: Document ID
            text: Text to append (with newlines)
        """
        # Get current document length
        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1
        
        # Insert text at the end
        requests = [
            {
                "insertText": {
                    "location": {"index": end_index},
                    "text": text + "\n\n",
                }
            }
        ]
        
        self.docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests},
        ).execute()
    
    def get_document_url(self, doc_id: str) -> str:
        """Get the URL for a Google Doc."""
        return f"https://docs.google.com/document/d/{doc_id}/edit"
