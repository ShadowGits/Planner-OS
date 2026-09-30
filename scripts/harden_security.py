"""Audit/revoke only public writer grants on tenant-owned Planner OS Drive IDs.

Use a private Cloud Run describe JSON (or an environment JSON object). Never
pass credentials as CLI values; this script never prints them. No Drive writes
occur unless --apply-drive is supplied. Existing reader/user/group grants and
inherited grants are preserved. The optional OAuth probe uses one synthetic,
short-lived record and cleans it up; it never redeems an existing user token.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.supabase.client import SupabaseConfig, SupabaseError, SupabaseRestClient
from adapters.supabase.oauth_state import SupabaseOAuthStateStore
from adapters.supabase.workspaces import SupabaseWorkspaceRepository
from planner_core.repository import PlannerCoreRepository
from planner_integrations.google_drive import get_drive_service


def load_private_environment(path: Path) -> None:
    data = json.loads(path.read_text())
    if "spec" in data:
        entries = data["spec"]["template"]["spec"]["containers"][0].get("env", [])
        data = {entry["name"]: entry["value"] for entry in entries if "value" in entry}
    for key, value in data.items():
        if isinstance(value, str):
            os.environ[key] = value


def revoke_public_writers(service, file_ids, *, apply=False):
    report = {"checked_files": 0, "public_writer_grants": 0, "revoked": 0, "inherited_skipped": 0, "errors": 0}
    audit = []
    for file_id in sorted(set(file_ids)):
        try:
            page_token = None
            while True:
                result = service.permissions().list(
                    fileId=file_id, fields="permissions(id,type,role,permissionDetails(inherited)),nextPageToken",
                    pageSize=100, pageToken=page_token,
                ).execute()
                for permission in result.get("permissions", []):
                    if permission.get("type") != "anyone" or permission.get("role") != "writer":
                        continue
                    report["public_writer_grants"] += 1
                    inherited = any(detail.get("inherited") for detail in permission.get("permissionDetails", []))
                    audit.append({"file_id": file_id, "permission": permission, "inherited": inherited})
                    if inherited:
                        report["inherited_skipped"] += 1
                    elif apply:
                        service.permissions().delete(fileId=file_id, permissionId=permission["id"]).execute()
                        report["revoked"] += 1
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            report["checked_files"] += 1
        except Exception:
            report["errors"] += 1
    return report, audit


def verify_atomic_oauth(gateway):
    store = SupabaseOAuthStateStore(gateway)
    key = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    try:
        store.put("auth_code", key, {"security_probe": True}, time.time() + 60)
        first = store.consume("auth_code", key)
        second = store.consume("auth_code", key)
        if first != {"security_probe": True} or second is not None:
            raise RuntimeError("Atomic OAuth DELETE RETURNING verification failed")
        return {"atomic_oauth_verified": True}
    finally:
        store.delete("auth_code", key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-json", type=Path, required=True)
    parser.add_argument("--apply-drive", action="store_true")
    parser.add_argument("--audit-drive", action="store_true")
    parser.add_argument("--verify-oauth", action="store_true")
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    load_private_environment(args.environment_json)
    gateway = SupabaseRestClient(SupabaseConfig.from_env())
    result = {}
    if args.verify_oauth:
        result.update(verify_atomic_oauth(gateway))
    if args.audit_drive or args.apply_drive:
        user_id = UUID(os.environ["MCP_USER_ID"])
        workspace = SupabaseWorkspaceRepository(gateway).get_active(user_id)
        if workspace is None:
            raise RuntimeError("Active workspace unavailable")
        repository = PlannerCoreRepository(gateway, user_id, workspace.id)
        projects = repository.list_rows("projects", strict=True)
        try:
            files = repository.list_rows("project_files", strict=True)
        except SupabaseError as error:
            if error.status_code != 404:
                raise
            result["project_file_tracking_table_unavailable"] = True
            files = []
        ids = [row["drive_folder_id"] for row in projects if row.get("drive_folder_id")]
        ids += [row["drive_file_id"] for row in files if row.get("drive_file_id") and row["drive_file_id"] != "dummy_id"]
        service = get_drive_service(SimpleNamespace(user_id=user_id), gateway, workspace.id)
        if service is None:
            raise RuntimeError("Workspace OAuth Drive connection is unavailable")
        result["known_drive_ids"] = len(set(ids))
        result["drive"], audit = revoke_public_writers(service, ids, apply=args.apply_drive)
        if args.audit_output:
            args.audit_output.write_text(json.dumps(audit, indent=2))
            args.audit_output.chmod(0o600)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Provider/transport exception text can include sensitive URLs or
        # credentials. Report only its class, retaining no secret output.
        print(json.dumps({"success": False, "error_type": type(error).__name__,
                          "http_status": getattr(error, "status_code", None)}), file=sys.stderr)
        sys.exit(1)
