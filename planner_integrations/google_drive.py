"""Google Drive integration for Planner OS project files."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]


def get_drive_service(user: Any | None = None, gateway: Any | None = None, workspace_id: Any | None = None) -> Any | None:
    """Initialize Google Drive client using user's OAuth credentials or fallback to service account."""
    if user and gateway:
        try:
            from adapters.supabase.calendar import SupabaseCalendarConnectionRepository
            from planner_platform.google_oauth import CredentialCipher
            from planner_platform.context import PlannerContext
            from uuid import UUID, uuid4
            from pathlib import Path
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            user_id = getattr(user, "user_id", user)
            # Use provided workspace_id or fallback to hardcoded test UUID
            if workspace_id:
                active_workspace_id = UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id
            else:
                active_workspace_id = UUID("1040706c-f046-4c27-bcc4-ca75c6ff7df3")

            ctx = PlannerContext(
                user_id=user_id,
                workspace_id=active_workspace_id,
                operation_id=uuid4(),
                workbook_path=Path("drive.xlsx"),
                timezone="UTC",
                execution_target="google_calendar",
                source_revision=0
            )
            client = getattr(gateway, "gateway", gateway)
            connections = SupabaseCalendarConnectionRepository(client)
            cipher = CredentialCipher.from_env()
            conn = connections.get(ctx.user_id, ctx.workspace_id)
            if conn and conn.status == "active":
                data = json.loads(cipher.decrypt(conn.encrypted_credentials, context=ctx))
                creds = Credentials.from_authorized_user_info(data, SCOPES)
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                svc = build("drive", "v3", credentials=creds)
                svc.files().list(pageSize=1, fields="files(id)").execute()
                return svc
        except Exception as e:
            logger.warning(f"Could not use user OAuth credentials for Drive: {e}")
            
    # If we get here, either user didn't exist, no gateway, no connections, or OAuth failed.
    # Return None so the application knows authentication failed (and can prompt user),
    # rather than falling back to the Service Account which would use the wrong quota.
    return None


def get_or_create_project_folder(service: Any, project_name: str, existing_folder_id: str | None = None) -> str | None:
    """Ensure a Google Drive subfolder exists for the project under the root Germany/Deutschland-Dash folder ID."""
    ROOT_GERMANY_FOLDER_ID = "11BSxfqTZmGOEDONsfpfuKtNHtR9dEFZi"

    if existing_folder_id:
        try:
            folder = service.files().get(fileId=existing_folder_id, fields="id, trashed").execute()
            if not folder.get("trashed", False):
                return existing_folder_id
        except Exception:
            logger.info(f"Folder ID {existing_folder_id} invalid or trashed; creating a new subfolder.")

    try:
        parent_id = ROOT_GERMANY_FOLDER_ID

        # Check if a subfolder with this project name already exists inside the root folder
        sub_query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{project_name}' and '{parent_id}' in parents and trashed = false"
        sub_results = service.files().list(q=sub_query, fields="files(id, name)").execute()
        sub_files = sub_results.get("files", [])

        if sub_files:
            return sub_files[0]["id"]
            
        project_folder_metadata = {
            "name": project_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }
        folder = service.files().create(body=project_folder_metadata, fields="id").execute()
        
        # Grant public link access to the folder if needed
        try:
            service.permissions().create(
                fileId=folder["id"],
                body={"type": "anyone", "role": "writer"}
            ).execute()
        except Exception as perm_err:
            logger.warning(f"Could not set public folder permissions: {perm_err}")

        return folder["id"]

    except Exception as e:
        logger.error(f"Error creating project subfolder: {e}")
        raise e


def create_drive_document(service: Any, folder_id: str, document_name: str, document_type: str = "text") -> dict[str, str] | None:
    """Create an empty Google Doc or Google Sheet in the specified folder."""
    mime_type = "application/vnd.google-apps.spreadsheet" if document_type == "excel" else "application/vnd.google-apps.document"
    
    file_metadata = {
        "name": document_name,
        "mimeType": mime_type,
        "parents": [folder_id]
    }

    try:
        file = service.files().create(body=file_metadata, fields="id, name, webViewLink").execute()
        file_id = file["id"]
        
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "writer"}
            ).execute()
        except Exception as perm_err:
            logger.warning(f"Could not set file permissions: {perm_err}")

        embed_link = f"https://docs.google.com/document/d/{file_id}/edit?embedded=true" if document_type == "text" else f"https://docs.google.com/spreadsheets/d/{file_id}/edit?embedded=true"

        return {
            "drive_file_id": file_id,
            "name": file.get("name", document_name),
            "drive_web_view_link": file.get("webViewLink"),
            "drive_embed_link": embed_link
        }
    except Exception as e:
        logger.error(f"Failed to create Drive document: {e}")
        return None


def upload_drive_file(service: Any, folder_id: str, file_name: str, file_bytes: bytes, content_type: str = "application/octet-stream") -> dict[str, str] | None:
    """Upload a local document or spreadsheet file to Google Drive folder."""
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload

    is_excel = any(ext in file_name.lower() for ext in ['.xls', '.xlsx', '.csv'])
    file_type = "excel" if is_excel else "text"

    file_metadata = {
        "name": file_name,
        "parents": [folder_id]
    }

    media = MediaIoBaseUpload(BytesIO(file_bytes), mimetype=content_type, resumable=False)

    try:
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, mimeType"
        ).execute()

        file_id = uploaded_file["id"]

        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "writer"}
            ).execute()
        except Exception as perm_err:
            logger.warning(f"Could not set file permissions: {perm_err}")

        embed_link = f"https://drive.google.com/file/d/{file_id}/preview"

        return {
            "drive_file_id": file_id,
            "name": uploaded_file.get("name", file_name),
            "file_type": file_type,
            "drive_web_view_link": uploaded_file.get("webViewLink"),
            "drive_embed_link": embed_link
        }
    except Exception as e:
        logger.error(f"Failed to upload Drive file: {e}")
        raise e


def download_drive_file(service: Any, file_id: str) -> bytes | None:
    """Download a file's raw content from Google Drive."""
    from googleapiclient.http import MediaIoBaseDownload
    from io import BytesIO

    try:
        request = service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        return fh.getvalue()
    except Exception as e:
        logger.error(f"Failed to download Drive file {file_id}: {e}")
        return None

