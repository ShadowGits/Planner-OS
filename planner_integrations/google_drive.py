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
    """Ensure a Google Drive folder exists for the project."""
    if not existing_folder_id and project_name.strip().lower() == "germany":
        existing_folder_id = "11BSxfqTZmGOEDONsfpfuKtNHtR9dEFZi"

    if existing_folder_id:
        try:
            folder = service.files().get(fileId=existing_folder_id, fields="id, trashed").execute()
            if not folder.get("trashed", False):
                return existing_folder_id
        except Exception:
            logger.info(f"Folder ID {existing_folder_id} invalid or trashed; creating a new one.")

    try:
        # 1. Ensure root 'Planner OS Projects' folder exists
        root_query = "mimeType = 'application/vnd.google-apps.folder' and name = 'Planner OS Projects' and trashed = false"
        results = service.files().list(q=root_query, fields="files(id, name)").execute()
        root_files = results.get("files", [])
        
        if root_files:
            parent_id = root_files[0]["id"]
        else:
            root_metadata = {
                "name": "Planner OS Projects",
                "mimeType": "application/vnd.google-apps.folder",
            }
            root_folder = service.files().create(body=root_metadata, fields="id").execute()
            parent_id = root_folder["id"]

        # 2. Check or create project subfolder
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
        logger.error(f"Error creating project folder: {e}")
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
