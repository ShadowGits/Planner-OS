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
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


def get_drive_service() -> Any | None:
    """Initialize Google Drive service account client."""
    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    creds_file = os.environ.get("GCP_SERVICE_ACCOUNT_FILE")
    
    try:
        if creds_json:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        elif creds_file and os.path.exists(creds_file):
            creds = service_account.Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        else:
            logger.warning("No GCP_SERVICE_ACCOUNT_JSON or GCP_SERVICE_ACCOUNT_FILE found in environment.")
            return None
            
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to initialize Google Drive service: {e}")
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
        return None


def create_drive_document(
    service: Any, 
    folder_id: str, 
    title: str, 
    file_type: str = "text"
) -> dict[str, Any] | None:
    """Create a Google Doc or Google Sheet inside the given folder."""
    mime_type_map = {
        "text": "application/vnd.google-apps.document",
        "excel": "application/vnd.google-apps.spreadsheet"
    }
    mime_type = mime_type_map.get(file_type, "application/vnd.google-apps.document")
    
    file_metadata = {
        "name": title,
        "mimeType": mime_type,
        "parents": [folder_id]
    }

    try:
        created_file = service.files().create(
            body=file_metadata,
            fields="id, name, webViewLink"
        ).execute()

        file_id = created_file["id"]

        # Grant 'anyone with link' writer permission so embedded iframe can view/edit
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "writer"}
            ).execute()
        except Exception as perm_err:
            logger.warning(f"Could not set file permissions: {perm_err}")

        # Construct embed link for iframe
        if file_type == "text":
            embed_link = f"https://docs.google.com/document/d/{file_id}/edit?embedded=true"
        elif file_type == "excel":
            embed_link = f"https://docs.google.com/spreadsheets/d/{file_id}/edit?embedded=true"
        else:
            embed_link = f"https://drive.google.com/file/d/{file_id}/preview"

        return {
            "drive_file_id": file_id,
            "name": created_file.get("name", title),
            "drive_web_view_link": created_file.get("webViewLink"),
            "drive_embed_link": embed_link
        }
    except Exception as e:
        logger.error(f"Failed to create Drive document: {e}")
        return None


def upload_drive_file(
    service: Any,
    folder_id: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream"
) -> dict[str, Any] | None:
    """Upload a local document or spreadsheet file to Google Drive folder."""
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload

    file_metadata = {
        "name": file_name,
        "parents": [folder_id]
    }
    media = MediaIoBaseUpload(BytesIO(file_bytes), mimetype=content_type, resumable=True)

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

        is_excel = any(ext in file_name.lower() for ext in ['.xls', '.xlsx', '.csv'])
        file_type = "excel" if is_excel else "text"
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
        return None
