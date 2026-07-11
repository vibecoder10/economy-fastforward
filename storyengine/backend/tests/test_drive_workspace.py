import pytest

import drive_workspace as workspace


class Request:
    def __init__(self, result=None, callback=None):
        self.result = result or {}
        self.callback = callback

    def execute(self):
        if self.callback:
            self.callback()
        return self.result


class Files:
    def __init__(self, client):
        self.client = client

    def update(self, fileId, body=None, **kwargs):
        def apply():
            if body and "name" in body:
                self.client.items[fileId]["name"] = body["name"]
        return Request({"id": fileId}, apply)


class Documents:
    def __init__(self, client):
        self.client = client

    def batchUpdate(self, documentId, body):
        self.client.formats[documentId] = body["requests"]
        return Request({})


class Service:
    def __init__(self, resource):
        self.resource = resource

    def files(self):
        return self.resource

    def documents(self):
        return self.resource


class FakeGoogleClient:
    parent_folder_id = "root"

    def __init__(self):
        self.items = {}
        self.bodies = {}
        self.formats = {}
        self.created = 0
        self.drive_service = Service(Files(self))
        self.docs_service = Service(Documents(self))

    def _new(self, name, parent, mime):
        self.created += 1
        item = {"id": f"id-{self.created}", "name": name, "parent": parent, "mimeType": mime}
        self.items[item["id"]] = item
        return item

    def search_folder(self, name, parent_id=None):
        return next((x for x in self.items.values() if x["name"] == name and x["parent"] == parent_id and x["mimeType"] == workspace.FOLDER_MIME), None)

    def get_or_create_folder(self, name, parent_id=None):
        return self.search_folder(name, parent_id) or self.create_folder(name, parent_id)

    def create_folder(self, name, parent_id=None):
        return self._new(name, parent_id, workspace.FOLDER_MIME)

    def search_file(self, name, folder_id):
        return next((x for x in self.items.values() if x["name"] == name and x["parent"] == folder_id), None)

    def create_document(self, name, folder_id=None):
        return self._new(name, folder_id, workspace.DOC_MIME)

    def replace_document_body(self, doc_id, text):
        self.bodies[doc_id] = text
        return True


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_refreshes_documents(monkeypatch):
    client = FakeGoogleClient()
    video = {
        "id": "video-1", "tenant_id": "tenant-1", "video_title": "Flying Machines",
        "research_payload": {"unit_roster": ["B-2 Spirit"], "fact_sheet": "First facts"},
        "script": "", "final_video_url": None, "drive_folder_id": None,
    }
    scenes = [{"scene": 1, "scene_text": "Opening narration."}]
    updates = []

    async def fetch_one(query, *args):
        return dict(video)

    async def fetch_all(query, *args):
        return list(scenes)

    async def execute(query, *args):
        updates.append(args)
        video["drive_folder_id"] = args[0]

    monkeypatch.setattr(workspace, "fetch_one", fetch_one)
    monkeypatch.setattr(workspace, "fetch_all", fetch_all)
    monkeypatch.setattr(workspace, "execute", execute)

    first = await workspace.sync_video_workspace("video-1", "tenant-1", client_factory=lambda: client)
    first_count = client.created
    assert set(first["folders"]) == {"images", "final_video"}
    assert set(first["docs"]) == {"machine_roster", "research", "script"}
    assert "B-2 Spirit" in client.bodies[first["docs"]["machine_roster"]]
    assert "Opening narration." in client.bodies[first["docs"]["script"]]
    assert client.formats[first["docs"]["research"]]

    video["research_payload"]["fact_sheet"] = "Refreshed facts"
    scenes[0]["scene_text"] = "Revised narration."
    second = await workspace.sync_video_workspace("video-1", "tenant-1", client_factory=lambda: client)

    assert client.created == first_count
    assert second["folder_id"] == first["folder_id"]
    assert second["docs"] == first["docs"]
    assert "Refreshed facts" in client.bodies[second["docs"]["research"]]
    assert "Revised narration." in client.bodies[second["docs"]["script"]]
    assert len(updates) == 2
    assert client.items[first["folder_id"]]["name"] == "Flying Machines — video-1"


@pytest.mark.asyncio
async def test_fail_soft_swallows_drive_outage(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("Drive offline")

    monkeypatch.setattr(workspace, "sync_video_workspace", broken)
    assert await workspace.sync_video_workspace_fail_soft("video-1", "tenant-1") is None


def test_seed_documents_have_clean_placeholders():
    assert "will appear here" in workspace._machine_roster_text("Title", {})
    assert "will appear here" in workspace._research_text("Title", {})
    assert "will appear here" in workspace._script_text("Title", "", [])


def test_duplicate_titles_still_get_unique_workspace_names():
    assert workspace._workspace_folder_name("Same title", "aaaaaaaa-1111") != workspace._workspace_folder_name("Same title", "bbbbbbbb-2222")


@pytest.mark.asyncio
async def test_production_sync_takes_and_releases_database_advisory_lock(monkeypatch):
    statements = []

    class Connection:
        async def execute(self, query, *args):
            statements.append((query, args))

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    async def get_pool():
        return Pool()

    async def unlocked(video_id, tenant_id=None, **kwargs):
        return {"video_id": video_id}

    monkeypatch.setattr(workspace, "get_pool", get_pool)
    monkeypatch.setattr(workspace, "_sync_video_workspace_unlocked", unlocked)

    result = await workspace.sync_video_workspace("video-1", "tenant-1")

    assert result == {"video_id": "video-1"}
    assert "pg_advisory_lock" in statements[0][0]
    assert "pg_advisory_unlock" in statements[-1][0]
