"""Google Drive and Docs API client."""

import os
import io
import time
from typing import Optional
import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError


class GoogleDocsUnavailableError(Exception):
    """Raised when Google Docs API is unavailable after retries."""
    pass


def get_direct_drive_url(drive_url: str) -> Optional[str]:
    """Convert Google Drive view URL to direct download URL.

    CRITICAL: Airtable attachment URLs expire after ~2 hours.
    Always use Google Drive permanent URLs for image-to-video and Remotion.

    Args:
        drive_url: Google Drive view URL (e.g., https://drive.google.com/file/d/FILE_ID/view)

    Returns:
        Direct download URL (e.g., https://drive.google.com/uc?export=download&id=FILE_ID)
        or None if conversion fails
    """
    if not drive_url:
        return None

    try:
        # Handle various Drive URL formats
        if "/file/d/" in drive_url:
            # Format: https://drive.google.com/file/d/FILE_ID/view
            file_id = drive_url.split("/file/d/")[1].split("/")[0]
        elif "id=" in drive_url:
            # Format: https://drive.google.com/uc?id=FILE_ID or ?export=download&id=FILE_ID
            file_id = drive_url.split("id=")[1].split("&")[0]
        elif "/open?id=" in drive_url:
            # Format: https://drive.google.com/open?id=FILE_ID
            file_id = drive_url.split("/open?id=")[1].split("&")[0]
        else:
            print(f"    ⚠️ Unknown Drive URL format: {drive_url[:50]}...")
            return None

        return f"https://drive.google.com/uc?export=download&id={file_id}"

    except (IndexError, AttributeError) as e:
        print(f"    ⚠️ Failed to parse Drive URL: {e}")
        return None


class GoogleClient:
    """Client for Google Drive and Docs APIs."""

    # Default folder ID from n8n workflow (Economy Fastforward folder)
    DEFAULT_PARENT_FOLDER_ID = "1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD"

    # Retry settings for transient errors
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1.0  # seconds
    
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

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Execute a function with exponential backoff retry on transient errors.

        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function

        Returns:
            Result of function call

        Raises:
            GoogleDocsUnavailableError: If all retries fail with 503
            HttpError: For non-transient errors
        """
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except HttpError as e:
                # Only retry on 503 Service Unavailable
                if e.resp.status == 503:
                    last_error = e
                    wait_time = self.INITIAL_BACKOFF * (2 ** attempt)
                    print(f"    Google API 503 error, retry {attempt + 1}/{self.MAX_RETRIES} in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise
        # All retries exhausted
        raise GoogleDocsUnavailableError(
            f"Google Docs API unavailable after {self.MAX_RETRIES} retries"
        ) from last_error

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

        def _create():
            return self.drive_service.files().create(
                body=file_metadata,
                fields="id, name, mimeType",
            ).execute()

        return self._retry_with_backoff(_create)
    
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

        def _search():
            return self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
            ).execute()

        results = self._retry_with_backoff(_search)
        files = results.get("files", [])
        return files[0] if files else None
    
    def search_folder_contains(self, name_part: str) -> Optional[dict]:
        """Search for a folder whose name contains the given string.

        Args:
            name_part: Partial folder name to search for

        Returns:
            First matching folder dict or None
        """
        results = self.search_folders_contains(name_part)
        return results[0] if results else None

    def search_folders_contains(self, name_part: str) -> list:
        """Search for ALL folders whose name contains the given string.

        Args:
            name_part: Partial folder name to search for

        Returns:
            List of matching folder dicts (id, name, mimeType)
        """
        escaped_name = name_part.replace("'", "\\'")
        query = f"name contains '{escaped_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"

        def _search():
            return self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
            ).execute()

        results = self._retry_with_backoff(_search)
        return results.get("files", [])

    def find_folder_by_keywords(self, title: str) -> list:
        """Find folders by keyword matching against the parent folder's subfolders.

        Useful when the title has changed since the folder was created.
        For example, title "China's $140B TRAP" should match folder
        "China's $140 Billion Liquidity Trap".

        Args:
            title: Video title to match against folder names

        Returns:
            List of (folder_dict, score) tuples, sorted by score descending.
            Score = number of matching keywords (3+ chars).
        """
        import re

        # List all subfolders in the parent folder
        query = (
            f"'{self.parent_folder_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )

        def _list():
            return self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
                pageSize=200,
            ).execute()

        results = self._retry_with_backoff(_list)
        folders = results.get("files", [])

        # Extract keywords from the title (words 3+ chars, lowercased)
        title_words = set(
            w.lower() for w in re.findall(r'[A-Za-z]+', title) if len(w) >= 3
        )

        if not title_words:
            return []

        scored = []
        for folder in folders:
            folder_words = set(
                w.lower() for w in re.findall(r'[A-Za-z]+', folder["name"]) if len(w) >= 3
            )
            overlap = title_words & folder_words
            if overlap:
                scored.append((folder, len(overlap)))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def search_file(self, name: str, folder_id: str) -> Optional[dict]:
        """Search for a file by name in a specific folder."""
        escaped_name = name.replace("'", "\\'")
        query = f"name = '{escaped_name}' and '{folder_id}' in parents and trashed = false"

        def _search():
            return self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
            ).execute()

        results = self._retry_with_backoff(_search)
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
            check_existing: If True, checks if file exists and replaces its content instead of creating duplicate

        Returns:
            Dict with file id, name, and mimeType
        """
        if check_existing:
            existing_file = self.search_file(name, folder_id)
            if existing_file:
                print(f"      found existing file: {name} ({existing_file['id']}), replacing content...")
                media = MediaIoBaseUpload(
                    io.BytesIO(content),
                    mimetype=mime_type,
                    resumable=True,
                )
                file_id = existing_file["id"]

                def _update():
                    return self.drive_service.files().update(
                        fileId=file_id,
                        media_body=media,
                        fields="id, name, mimeType",
                    ).execute()

                return self._retry_with_backoff(_update)

        file_metadata = {
            "name": name,
            "parents": [folder_id],
        }

        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=mime_type,
            resumable=True,
        )

        def _upload():
            return self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, mimeType",
            ).execute()

        return self._retry_with_backoff(_upload)
    
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

    def download_file_to_local(self, file_id: str, local_path: str) -> str:
        """Download a file from Google Drive to local filesystem.

        Args:
            file_id: Google Drive file ID
            local_path: Local file path to save to

        Returns:
            The local_path on success

        Raises:
            Exception on download failure
        """
        import io as _io
        from googleapiclient.http import MediaIoBaseDownload

        def _download():
            request = self.drive_service.files().get_media(fileId=file_id)
            fh = _io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return fh.getvalue()

        content = self._retry_with_backoff(_download)

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)
        return local_path

    def make_file_public(self, file_id: str) -> str:
        """Make a file public and return its direct download link (webContentLink)."""
        def _set_permission():
            self.drive_service.permissions().create(
                fileId=file_id,
                body={"role": "reader", "type": "anyone"},
            ).execute()

        def _get_link():
            return self.drive_service.files().get(
                fileId=file_id,
                fields="webContentLink"
            ).execute()

        self._retry_with_backoff(_set_permission)
        file = self._retry_with_backoff(_get_link)
        return file.get("webContentLink")

    def get_direct_drive_url(self, url_or_id: str) -> str:
        """Convert a Google Drive view URL or file ID to a direct download URL.

        Grok Imagine and other video generation APIs require direct download URLs,
        not Drive viewer URLs. This helper handles the conversion.

        Handles multiple URL formats:
        - https://drive.google.com/file/d/FILE_ID/view
        - https://drive.google.com/open?id=FILE_ID
        - https://drive.google.com/uc?id=FILE_ID (already direct)
        - https://drive.google.com/uc?export=download&id=FILE_ID (already direct)
        - Raw FILE_ID

        Args:
            url_or_id: A Drive URL or file ID

        Returns:
            Direct download URL: https://drive.google.com/uc?export=download&id=FILE_ID
        """
        import re

        if not url_or_id:
            return url_or_id

        # If already a direct download URL, return as-is
        if "export=download" in url_or_id:
            return url_or_id

        # If it's a uc?id= URL, add export=download
        if "uc?id=" in url_or_id:
            file_id_match = re.search(r'id=([a-zA-Z0-9_-]+)', url_or_id)
            if file_id_match:
                return f"https://drive.google.com/uc?export=download&id={file_id_match.group(1)}"

        # Extract file ID from various URL formats
        file_id = None

        patterns = [
            r'/file/d/([a-zA-Z0-9_-]+)',   # /file/d/FILE_ID/view
            r'[?&]id=([a-zA-Z0-9_-]+)',     # ?id=FILE_ID or &id=FILE_ID
            r'^([a-zA-Z0-9_-]{20,})$',      # Raw file ID (20+ chars, no slashes)
        ]

        for pattern in patterns:
            match = re.search(pattern, url_or_id)
            if match:
                file_id = match.group(1)
                break

        if not file_id:
            # Return original if can't parse (may already be usable or a different URL type)
            return url_or_id

        return f"https://drive.google.com/uc?export=download&id={file_id}"

    def list_files_in_folder(self, folder_id: str) -> list:
        """List all files in a Google Drive folder.

        Args:
            folder_id: The folder ID to list files from

        Returns:
            List of dicts with id, name, and mimeType
        """
        query = f"'{folder_id}' in parents and trashed = false"

        def _list():
            return self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType, size)",
                pageSize=200,
            ).execute()

        results = self._retry_with_backoff(_list)
        return results.get("files", [])

    def download_file(self, file_id: str) -> bytes:
        """Download a file's content from Google Drive.

        Args:
            file_id: The file ID to download

        Returns:
            File content as bytes
        """
        def _download():
            return self.drive_service.files().get_media(fileId=file_id).execute()

        return self._retry_with_backoff(_download)

    # ==================== DOCS OPERATIONS ====================
    
    def create_document(self, title: str, folder_id: Optional[str] = None) -> dict:
        """Create a new Google Doc.

        Args:
            title: Document title
            folder_id: Folder to create doc in (if specified, doc will be moved there)

        Returns:
            Dict with document id, title, and 'unavailable' flag if API is down
        """
        try:
            def _create():
                return self.docs_service.documents().create(
                    body={"title": title}
                ).execute()

            doc = self._retry_with_backoff(_create)
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
                "unavailable": False,
            }
        except GoogleDocsUnavailableError:
            print(f"    ⚠️  Google Docs API unavailable - continuing without doc")
            return {
                "id": None,
                "title": title,
                "unavailable": True,
            }
    
    def append_to_document(self, doc_id: Optional[str], text: str) -> bool:
        """Append text to a Google Doc.

        Args:
            doc_id: Document ID (None if doc unavailable)
            text: Text to append (with newlines)

        Returns:
            True if successful, False if unavailable or failed
        """
        if not doc_id:
            # Doc was never created (API was down)
            return False

        try:
            def _append():
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

            self._retry_with_backoff(_append)
            return True
        except GoogleDocsUnavailableError:
            print(f"    ⚠️  Google Docs API unavailable - scene saved to Airtable only")
            return False
    
    def get_document_url(self, doc_id: Optional[str]) -> Optional[str]:
        """Get the URL for a Google Doc."""
        if not doc_id:
            return None
        return f"https://docs.google.com/document/d/{doc_id}/edit"
