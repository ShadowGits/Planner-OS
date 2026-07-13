"""Private deterministic Supabase workbook object storage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from adapters.supabase.client import SupabaseGateway
from planner_platform.context import PlannerContext


WORKBOOK_BUCKET = "planner-workbooks"
WORKBOOK_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_WORKBOOK_BYTES = 50 * 1024 * 1024


def workspace_object_key(user_id: UUID, workspace_id: UUID) -> str:
    if not isinstance(user_id, UUID) or not isinstance(workspace_id, UUID):
        raise TypeError("Workbook object keys require UUID user and workspace identifiers")
    return f"{user_id}/{workspace_id}/current.xlsx"


def workspace_rules_key(user_id: UUID, workspace_id: UUID) -> str:
    if not isinstance(user_id, UUID) or not isinstance(workspace_id, UUID):
        raise TypeError("Rules object keys require UUID user and workspace identifiers")
    return f"{user_id}/{workspace_id}/rules.yaml"


class SupabaseWorkbookObjectStore:
    def __init__(self, client: SupabaseGateway, bucket: str = WORKBOOK_BUCKET) -> None:
        if bucket != WORKBOOK_BUCKET:
            raise ValueError("Planner workbooks must use the private planner-workbooks bucket")
        self.client = client
        self.bucket = bucket

    def download_current(self, context: PlannerContext, destination_dir: Path) -> Path:
        content = self.client.storage_download(
            self.bucket,
            workspace_object_key(context.user_id, context.workspace_id),
        )
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / "current.xlsx"
        destination.write_bytes(content)
        return destination

    def upload_current(self, context: PlannerContext, source: Path) -> None:
        content = self._validated_workbook(source)
        self.client.storage_upload(
            self.bucket,
            workspace_object_key(context.user_id, context.workspace_id),
            content,
            content_type=WORKBOOK_CONTENT_TYPE,
            upsert=True,
        )

    def backup_current(self, context: PlannerContext, checksum: str) -> str:
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum.casefold()):
            raise ValueError("Invalid workbook SHA-256 checksum")
        current_key = workspace_object_key(context.user_id, context.workspace_id)
        content = self.client.storage_download(self.bucket, current_key)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_key = (
            f"{context.user_id}/{context.workspace_id}/backups/"
            f"{context.source_revision}-{timestamp}-{checksum.casefold()}.xlsx"
        )
        self.client.storage_upload(
            self.bucket,
            backup_key,
            content,
            content_type=WORKBOOK_CONTENT_TYPE,
            upsert=False,
        )
        return backup_key

    def download_rules(self, context: PlannerContext, destination_dir: Path) -> Path | None:
        try:
            content = self.client.storage_download(
                self.bucket,
                workspace_rules_key(context.user_id, context.workspace_id),
            )
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / "rules.yaml"
            destination.write_bytes(content)
            return destination
        except Exception as e:
            # If the file doesn't exist, storage_download will raise an error.
            # We treat any download failure here as "no custom rules exist yet".
            return None

    def upload_rules(self, context: PlannerContext, source: Path) -> None:
        if source.name != "rules.yaml" or not source.is_file():
            raise ValueError("Rules source must be an existing rules.yaml file")
        content = source.read_bytes()
        self.client.storage_upload(
            self.bucket,
            workspace_rules_key(context.user_id, context.workspace_id),
            content,
            content_type="text/yaml",
            upsert=True,
        )

    @staticmethod
    def _validated_workbook(source: Path) -> bytes:
        if source.suffix.casefold() != ".xlsx" or not source.is_file():
            raise ValueError("Workbook source must be an existing .xlsx file")
        size = source.stat().st_size
        if size <= 0 or size > MAX_WORKBOOK_BYTES:
            raise ValueError("Workbook size is outside the allowed range")
        return source.read_bytes()
