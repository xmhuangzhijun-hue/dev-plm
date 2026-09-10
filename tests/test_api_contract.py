"""HTTP boundary tests only; this test double is not a persistent backend."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.routes import create_app
from backend.protocol import Identity, ServiceError
from backend.schema_diff import compare_contract, normalize_schema
from backend.documentation import apply_documentation

TIME = "2026-09-05T12:00:00Z"


class BoundaryDouble:
    """Tests transport/authorization only, never advertised as DB acceptance."""
    def __init__(self):
        self.calls = []
        self.fail_conflict = False
        self.discussion = {"id": "d1", "project_id": "p1", "target_id": "r1", "body": "Initial body",
            "revision": 1, "authority": "database", "export_status": "not_exported", "created_by": "alice",
            "created_at": TIME, "updated_by": "alice", "updated_at": TIME, "deleted_at": None}
        self.post = {"id": "post1", "project_id": "p1", "discussion_id": "d1", "parent_post_id": None,
            "body": "Reply body", "revision": 1, "authority": "database", "export_status": "not_exported",
            "created_by": "alice", "created_at": TIME, "updated_by": "alice", "updated_at": TIME, "deleted_at": None}
        self.notification = {"id": "n1", "project_id": "p1", "recipient_id": "alice", "payload": {"target_id": "r1"},
                             "created_at": TIME, "read_at": None, "revision": 1}

    def issue_token(self, identifier, credential):
        raise ServiceError(401, "INVALID_CREDENTIALS", "测试替身不签发有效令牌。")

    def list_projects(self, identity):
        self.calls.append(("list_projects", identity))
        return []

    def list_requirements(self, identity, project_id):
        return []

    def list_requirement_changes(self, identity, project_id, requirement_id):
        self.calls.append(("list_requirement_changes", identity, project_id, requirement_id))
        return []

    def get_change_diff(self, identity, project_id, change_id):
        return {"change_id": change_id, "status": "partial", "source": "git", "notice": "binary test",
                "files": [{"path": "image.bin", "added": None, "deleted": None, "hunks": []}]}

    def create_discussion(self, identity, project_id, body, key, request_id):
        self.calls.append(("create_discussion", identity, project_id, body, key, request_id))
        return {**self.discussion, "project_id": project_id, "target_id": body["target_id"], "body": body["body"]}

    def get_discussion(self, identity, discussion_id):
        return deepcopy(self.discussion)

    def get_post(self, identity, post_id):
        return deepcopy(self.post)

    def _edit(self, operation, resource, identity, id, body, key, request_id):
        self.calls.append((operation, identity, id, body, key, request_id))
        if self.fail_conflict:
            raise ServiceError(409, "REVISION_CONFLICT", "Alice 在所示时间修改了 body。", {
                "current_revision": 2, "changed_by": {"id": "alice", "display_name": "Alice"},
                "changed_at": TIME, "changed_fields": ["body"], "before": {"body": "before"}, "after": {"body": "after"}})
        return {**resource, "body": body.get("body", ""), "revision": body["revision"] + 1}

    def update_discussion(self, *args):
        return self._edit("update_discussion", self.discussion, *args)

    def delete_discussion(self, *args):
        return self._edit("delete_discussion", self.discussion, *args)

    def update_post(self, *args):
        return self._edit("update_post", self.post, *args)

    def delete_post(self, *args):
        return self._edit("delete_post", self.post, *args)

    def get_notification(self, identity, id):
        return deepcopy(self.notification)

    def update_notification(self, identity, id, body, key, request_id):
        self.calls.append(("update_notification", identity, id, body, key, request_id))
        return {**self.notification, "read_at": TIME, "revision": body["revision"] + 1}


@pytest.fixture
def boundary():
    service = BoundaryDouble()
    identities = {"owner": Identity("tenant-test", "alice", "owner"),
                  "other": Identity("tenant-test", "bob", "maintainer"),
                  "viewer": Identity("tenant-test", "viewer", "viewer")}

    def authenticate(token):
        if token not in identities:
            raise ServiceError(401, "AUTH_REQUIRED", "没有有效访问令牌。")
        return identities[token]

    app = create_app(service, authenticate)
    return service, app, TestClient(app)


def headers(actor="owner", key="test-key"):
    return {"Authorization": "Bearer " + actor, "Idempotency-Key": key}


def test_native_generated_openapi_keeps_original_operations(boundary):
    _, app, _ = boundary
    assert app.openapi.__func__ is FastAPI.openapi
    generated = app.openapi()
    ids = {op["operationId"] for item in generated["paths"].values() for method, op in item.items() if method in {"get", "post", "patch", "delete"}}
    assert {"issueAccessToken", "listProjects", "listRequirements", "listRequirementChanges", "getChangeDiff",
            "startProjection", "getProjection", "createDiscussion", "updateClaim", "exportCollaboration", "getCollaborationExport"} <= ids
    assert len(ids) == 26
    for item in generated["paths"].values():
        for method, operation in item.items():
            if method in {"get", "post", "patch", "delete"}:
                assert operation["responses"]["503"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Error"}


def test_auth_is_required_and_identity_is_not_client_body(boundary):
    service, _, client = boundary
    assert client.get("/v1/projects").status_code == 401
    assert client.get("/v1/projects", headers=headers()).status_code == 200
    assert service.calls[-1][1] == Identity("tenant-test", "alice", "owner")
    bad = client.post("/v1/projects/p1/discussions", headers=headers(), json={"target_id": "r1", "body": "hello", "tenant_id": "someone-else"})
    assert bad.status_code == 422


def test_viewer_cannot_write_and_service_is_not_called(boundary):
    service, _, client = boundary
    response = client.post("/v1/projects/p1/discussions", headers=headers("viewer"), json={"target_id": "r1", "body": "hello"})
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert not service.calls


@pytest.mark.parametrize("path", ["/v1/projects", "/v1/projects/p1", "/v1/projects/p1/requirements", "/v1/requirements/r1", "/v1/changes/c1/diff", "/v1/principals"])
def test_file_and_git_facts_reject_writes_explicitly(boundary, path):
    service, _, client = boundary
    response = client.patch(path, headers=headers(), json={"title": "cannot mutate"})
    assert response.status_code == 405
    assert response.json()["code"] == "FILE_FACTS_READ_ONLY"
    assert not service.calls


def test_discussion_body_and_idempotency_context_reach_service(boundary):
    service, _, client = boundary
    response = client.post("/v1/projects/p1/discussions", headers=headers(key="stable-test-key"), json={"target_id": "r1", "body": "Real initial body"})
    assert response.status_code == 201
    assert response.json()["body"] == "Real initial body"
    assert service.calls[-1][4] == "stable-test-key"
    assert service.calls[-1][5].startswith("REQ-")


@pytest.mark.parametrize("method,path,payload", [("patch", "/v1/discussions/d1", {"body": "edit", "revision": 1}),
    ("delete", "/v1/discussions/d1", {"revision": 1}), ("patch", "/v1/discussion-posts/post1", {"body": "edit", "revision": 1}),
    ("delete", "/v1/discussion-posts/post1", {"revision": 1})])
def test_others_cannot_edit_or_delete_statements(boundary, method, path, payload):
    service, _, client = boundary
    response = client.request(method, path, headers=headers("other"), json=payload)
    assert response.status_code == 403
    assert not service.calls


def test_revision_error_keeps_who_when_what(boundary):
    service, _, client = boundary
    service.fail_conflict = True
    response = client.patch("/v1/discussion-posts/post1", headers=headers(), json={"body": "edit", "revision": 1})
    assert response.status_code == 409
    conflict = response.json()["conflict"]
    assert conflict["changed_by"] == {"id": "alice", "display_name": "Alice"}
    assert conflict["changed_at"] == TIME
    assert conflict["changed_fields"] == ["body"]
    assert conflict["before"] != conflict["after"]


def test_project_scope_is_required_for_legacy_global_ids(boundary):
    service, _, client = boundary
    assert client.get("/v1/requirements/r1/changes", headers=headers()).status_code == 422
    response = client.get("/v1/requirements/r1/changes?project_id=p1", headers=headers())
    assert response.status_code == 200
    assert service.calls[-1][2:] == ("p1", "r1")


def test_partial_and_binary_null_survive_response_validation(boundary):
    _, _, client = boundary
    response = client.get("/v1/changes/c1/diff?project_id=p1", headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["files"][0]["added"] is None


def test_notifications_can_only_be_marked_by_recipient(boundary):
    service, _, client = boundary
    assert client.patch("/v1/notifications/n1", headers=headers("other"), json={"read": True, "revision": 1}).status_code == 403
    response = client.patch("/v1/notifications/n1", headers=headers(), json={"read": True, "revision": 1})
    assert response.status_code == 200
    assert response.json()["read_at"] == TIME


def test_validation_errors_never_echo_credentials(boundary):
    _, _, client = boundary
    marker = "TEST_ONLY_NEVER_ECHO_THIS_INPUT"
    response = client.post("/v1/auth/token", json={"identifier": "", "credential": marker})
    assert response.status_code == 422
    assert marker not in response.text


def tiny_app(min_length=1, status=200):
    class Message(BaseModel):
        model_config = ConfigDict(extra="forbid")
        message: str = Field(min_length=min_length)
    app = FastAPI()

    @app.post("/echo", operation_id="echo", response_model=Message, status_code=status,
              responses={422: {"description": "Invalid input"}})
    def echo(body: Message):
        return body
    return app


def tiny_reviewed():
    # Handwritten independent baseline. It is not generated by the app/model.
    schema = {"type": "object", "properties": {"message": {"type": "string", "minLength": 1}},
              "required": ["message"], "additionalProperties": False}
    content = {"application/json": {"schema": schema}}
    return {"openapi": "3.1.0", "info": {"title": "Reviewed", "version": "1"}, "paths": {"/echo": {"post": {
        "operationId": "echo", "requestBody": {"required": True, "content": content},
        "responses": {"200": {"description": "Success", "content": deepcopy(content)}, "422": {"description": "Invalid input"}}}}}}


def test_independent_generated_schema_agrees_with_handwritten_baseline():
    assert compare_contract(tiny_reviewed(), tiny_app().openapi()) == []


def test_real_model_drift_fails_with_request_and_response_paths():
    differences = compare_contract(tiny_reviewed(), tiny_app(min_length=2).openapi())
    pointers = [difference["pointer"] for difference in differences]
    assert any("requestBody" in path and path.endswith("minLength") for path in pointers)
    assert any("responses/200" in path and path.endswith("minLength") for path in pointers)


def test_status_and_security_drift_are_not_ignored():
    reviewed = tiny_reviewed()
    differences = compare_contract(reviewed, tiny_app(status=201).openapi())
    assert any(difference["pointer"].endswith("responses/201") for difference in differences)
    generated = tiny_app().openapi()
    generated["security"] = [{"bearerAuth": []}]
    generated["components"]["securitySchemes"] = {"bearerAuth": {"type": "http", "scheme": "bearer"}}
    assert any(difference["pointer"].endswith("/security") for difference in compare_contract(reviewed, generated))


def test_nullable_and_const_normalization_are_equivalent():
    left = {"type": ["integer", "null"], "minimum": 0}
    right = {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}
    assert normalize_schema(left, {}) == normalize_schema(right, {})
    assert normalize_schema({"type": "string", "const": "git"}, {}) == normalize_schema({"type": "string", "enum": ["git"]}, {})
    nullable_enum = {"anyOf": [{"type": "string", "enum": ["active"]}, {"type": "null"}]}
    assert normalize_schema(nullable_enum, {}) == normalize_schema({"type": ["string", "null"], "enum": ["active", None]}, {})


def test_property_named_title_is_not_removed_as_documentation():
    left = {"type": "object", "properties": {"title": {"type": "string"}}}
    right = {"type": "object", "properties": {"title": {"type": "integer"}}}
    assert normalize_schema(left, {}) != normalize_schema(right, {})


def test_documentation_overlay_cannot_change_schemas_paths_or_statuses():
    app = tiny_app()
    before = app.openapi()
    source = tiny_reviewed()
    operation = source["paths"]["/echo"]["post"]
    operation["requestBody"]["content"]["application/json"]["schema"] = {"type": "integer"}
    operation["requestBody"]["content"]["application/json"]["examples"] = {"sample": {"value": {"message": "hello"}}}
    operation["responses"]["599"] = {"description": "Cannot add this status"}
    source["paths"]["/invented"] = deepcopy(source["paths"]["/echo"])
    apply_documentation(app, source)
    after = app.openapi()
    assert app.openapi.__func__ is FastAPI.openapi
    assert compare_contract(before, after) == []
    assert "/invented" not in after["paths"]
    assert "599" not in after["paths"]["/echo"]["post"]["responses"]
    assert "examples" in after["paths"]["/echo"]["post"]["requestBody"]["content"]["application/json"]
