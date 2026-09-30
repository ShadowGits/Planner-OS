from types import SimpleNamespace

from planner_integrations.google_drive import create_drive_document, get_drive_service, get_or_create_project_folder, upload_drive_file
from scripts.harden_security import revoke_public_writers


class Drive:
    def __init__(self):
        self.calls = []
        self.response = {}
    def files(self):
        return self
    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        self.response = {"files": []}
        return self
    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        self.response = {"id": "new-id", "name": kwargs["body"]["name"], "webViewLink": "https://docs.google.com/example"}
        return self
    def execute(self):
        return self.response
    def permissions(self):
        raise AssertionError("Creating files must never grant public permissions")


def test_folder_name_is_escaped_in_drive_query(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "private-root")
    drive = Drive()
    assert get_or_create_project_folder(drive, "Sparsh's \\ notes") == "new-id"
    query = drive.calls[0][1]["q"]
    assert "name = 'Sparsh\\'s \\\\ notes'" in query
    assert "'private-root' in parents" in query


def test_new_root_and_documents_remain_private(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", raising=False)
    drive = Drive()
    get_or_create_project_folder(drive, "Study")
    root = next(kwargs["body"] for kind, kwargs in drive.calls if kind == "create")
    assert root["name"] == "Planner OS"
    assert "parents" not in root
    assert root["appProperties"] == {"planner_os_root": "true"}
    assert create_drive_document(drive, "folder", "My private doc")["drive_file_id"] == "new-id"
    assert upload_drive_file(drive, "folder", "notes.txt", b"private")["drive_file_id"] == "new-id"


def test_authenticated_user_cannot_fallback_to_shared_service_account(monkeypatch):
    import planner_integrations.google_drive as integration
    monkeypatch.setattr(integration, "_get_service_account_drive", lambda: (_ for _ in ()).throw(AssertionError("shared account used")))
    assert get_drive_service(SimpleNamespace(user_id="mine"), object(), None, allow_service_account=True) is None


def test_remediation_only_revokes_direct_public_writer_grants():
    class Permissions:
        def __init__(self):
            self.deleted = []
            self.result = None
        def permissions(self):
            return self
        def list(self, **kwargs):
            self.result = {"permissions": [
                {"id": "writer", "type": "anyone", "role": "writer"},
                {"id": "reader", "type": "anyone", "role": "reader"},
                {"id": "user", "type": "user", "role": "writer"},
                {"id": "inherited", "type": "anyone", "role": "writer", "permissionDetails": [{"inherited": True}]},
            ]}
            return self
        def delete(self, **kwargs):
            self.deleted.append(kwargs)
            self.result = {}
            return self
        def execute(self):
            return self.result
    drive = Permissions()
    report, audit = revoke_public_writers(drive, ["owned-id"], apply=False)
    assert report["public_writer_grants"] == 2
    assert drive.deleted == []
    report, audit = revoke_public_writers(drive, ["owned-id"], apply=True)
    assert report["revoked"] == 1
    assert report["inherited_skipped"] == 1
    assert drive.deleted == [{"fileId": "owned-id", "permissionId": "writer"}]
