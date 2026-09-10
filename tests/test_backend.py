"""Real PostgreSQL acceptance; disabled unless explicitly authorized and enabled.

Run only after local database/role/credential setup is approved:
    $env:DEVPLM_RUN_POSTGRES_TESTS = "1"
    python -m pytest tests/test_backend.py -q

Every test creates its own devplm_rebuild_<uuid> database and removes only that
database. No SQLite/in-memory repositories, fake authentication, or mocked DB
connections are used. Collection imports no backend app/config and reads no
credentials. Missing configured runtime prerequisites are failures when enabled.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import Barrier, Event
from contextvars import ContextVar
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[1]
ACTORS = ("owner", "maintainer", "viewer", "other-owner", "outsider")
DB_PATTERN = re.compile(r"devplm_rebuild_[0-9a-f]{32}\Z")
pytestmark = pytest.mark.skipif(
    os.environ.get("DEVPLM_RUN_POSTGRES_TESTS") != "1",
    reason="Real PostgreSQL acceptance is not enabled; no DB/config/secret access occurred.",
)


def _checked_database(name):
    if not DB_PATTERN.fullmatch(name):
        raise ValueError("Refusing to manage a database outside the test prefix")
    return name


def _safe_status(response, expected, method="request", path=""):
    """Avoid rendering Request objects, headers, auth bodies, or response tokens."""
    if response.status_code != expected:
        try:
            code = response.json().get("code", "UNEXPECTED_RESPONSE")
        except (ValueError, AttributeError):
            code = "NON_JSON_RESPONSE"
        safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Z_]+", code) else "UNEXPECTED_RESPONSE"
        raise AssertionError(f"{method} {path}: HTTP {response.status_code}, expected {expected}, code={safe_code}")


class Runtime:
    """Business-only test harness; its repr never includes tokens or credentials."""
    def __init__(self, directory, code, sources, db, client, services, loader, bindings, read_secret):
        self.directory, self.code, self.sources = directory, code, sources
        self.db, self.client, self.services, self.load = db, client, services, loader
        self._tokens = {}
        for actor in ACTORS:
            candidates = [row for row in bindings if row.get("identifier") == actor]
            if len(candidates) != 1:
                pytest.fail(f"Integration identity registration is missing or ambiguous: {actor}", pytrace=False)
            row = candidates[0]
            tenant = "isolated-demo" if actor == "outsider" else "devplm-local"
            if (row.get("principal_id"), row.get("tenant_id")) != (actor, tenant):
                pytest.fail(f"Integration identity registration has unexpected scope: {actor}", pytrace=False)
            response = client.post("/v1/auth/token", json={
                "identifier": actor, "credential": read_secret(row["credential_ref"]),
            })
            _safe_status(response, 200, "POST", "/v1/auth/token")
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                pytest.fail("Authentication did not issue a valid token", pytrace=False)
            self._tokens[actor] = token
        requirements = self.request("owner", "GET", "/v1/projects/dev-plm/requirements")["items"]
        self.target = requirements[0]["id"]

    def request(self, actor, method, path, body=None, *, expected=200, key=None, client=None):
        headers = {"Authorization": "Bearer " + self._tokens[actor]} if actor else {}
        if method in ("POST", "PATCH", "DELETE", "PUT"):
            headers["Idempotency-Key"] = key or "test-" + uuid4().hex
        response = (client or self.client).request(method, path, headers=headers, json=body)
        _safe_status(response, expected, method, path)
        return response.json()

    def discussion(self, actor="owner", body="Explicit fictional integration discussion", key=None):
        return self.request(actor, "POST", "/v1/projects/dev-plm/discussions",
            {"target_id": self.target, "body": body}, expected=201, key=key)

    def claim(self, actor="owner", claimant="maintainer", key=None):
        return self.request(actor, "POST", "/v1/projects/dev-plm/claims",
            {"target_id": self.target, "claimant_id": claimant}, expected=201, key=key)

    def facts(self):
        with self.db.connection() as conn:
            return self.db.fact_digest(conn)

    def collaboration(self):
        from psycopg import sql
        with self.db.connection() as conn:
            return {table: self.db.digest(conn.execute(sql.SQL("SELECT * FROM devplm.{} ORDER BY pk").format(
                sql.Identifier(table))).fetchall()) for table in self.db.D_TABLES}

    def count(self, table):
        from psycopg import sql
        if table not in self.db.D_TABLES + self.db.E_TABLES:
            raise ValueError("Only known runtime tables can be counted")
        with self.db.connection() as conn:
            return conn.execute(sql.SQL("SELECT count(*) AS n FROM devplm.{}").format(sql.Identifier(table))).fetchone()["n"]


def _make_sources(directory):
    """Clone ordinary sources; all fixture edits and exports stay under .work."""
    import yaml
    code, sources, history = directory / "code", directory / "data", directory / "history"
    code.mkdir()
    # Stop Git parent discovery at the fixture root. Otherwise copied relative
    # history references accidentally read the developer's outer repository.
    subprocess.run(['git','init','--quiet',str(directory)],check=True,capture_output=True)
    shutil.copytree(ROOT / "src", code / "src")
    shutil.copytree(ROOT / "projects", sources, ignore=shutil.ignore_patterns("collaboration-exports"))
    shutil.copy2(ROOT / "build.py", code / "build.py")
    # The self-project declares real tools/backend source entries. Preserve
    # those bytes in the isolated fixture so shared source validation can run.
    for name in ('tools', 'backend'):
        shutil.copytree(ROOT / name, code / name, ignore=shutil.ignore_patterns('__pycache__'))
    # Real independent Git commits make the API diff test reproducible.
    history.mkdir()
    def git(*args):
        result = subprocess.run(["git", "-C", str(history), *args], shell=False,
            capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
        return result.stdout.strip()
    git("init", "--quiet")
    (history / "notes.txt").write_text("alpha\nkeep\n", encoding="utf-8", newline="\n")
    (history / "image.bin").write_bytes(b"\x00first")
    git("add", "--", "notes.txt", "image.bin")
    git("-c", "user.name=Explicit fictional fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Fictional integration baseline")
    (history / "notes.txt").write_text("alpha\nchanged\nextra\n", encoding="utf-8", newline="\n")
    (history / "image.bin").write_bytes(b"\x00second")
    git("add", "--", "notes.txt", "image.bin")
    git("-c", "user.name=Explicit fictional fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Fictional integration exact difference")
    commit = git("rev-parse", "HEAD")
    requirement_file = sorted((sources / "dev-plm/requirements").glob("*.md"))[0]
    requirement = yaml.safe_load(requirement_file.read_text(encoding="utf-8").split("---", 2)[1])["id"]
    change = {"id": "CHG-INTEGRATION-FACTS", "title": "Explicit fictional Git acceptance fixture",
              "reqs": [requirement], "status": "fictional-test", "repo": history.as_posix(), "commit": commit}
    (sources / "dev-plm/changes/CHG-INTEGRATION-FACTS.md").write_text(
        "---\n" + yaml.safe_dump(change, allow_unicode=True, sort_keys=False) +
        "---\nExplicit fictional acceptance data; not real product history.\n", encoding="utf-8")
    return code, sources


@pytest.fixture
def runtime(monkeypatch):
    # This body is unreachable during collection or a normal, unapproved run.
    if os.environ.get("DEVPLM_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("Real PostgreSQL acceptance was not enabled")
    try:
        from psycopg import sql
        from fastapi.testclient import TestClient
        import build
        from backend import db, config
        from backend.manage import provision_logins
        from backend.services import Services
        from backend.app import make_app
    except ImportError:
        pytest.fail("Approved PostgreSQL acceptance dependencies are unavailable; no fallback DB is used", pytrace=False)
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    name = _checked_database("devplm_rebuild_" + uuid4().hex)
    created = False
    with tempfile.TemporaryDirectory(prefix="backend-acceptance-", dir=work) as temporary:
        directory = Path(temporary).resolve()
        if not directory.is_relative_to(work.resolve()):
            pytest.fail("Integration fixture path escaped .work", pytrace=False)
        code, sources = _make_sources(directory)
        loader = lambda: build.load_workspace(code, data_roots=[sources])
        payload = loader()  # Validate sources before performing DB setup.
        try:
            monkeypatch.setenv("DEVPLM_DB_NAME", "postgres")
            with db.connection("admin") as admin:
                admin.autocommit = True
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_checked_database(name))))
                created = True
            monkeypatch.setenv("DEVPLM_DB_NAME", name)
            with db.connection("admin") as conn:
                db.migrate(conn)
                provision_logins(conn)
            with db.connection("sync") as conn:
                db.sync(conn, payload)
            services = Services(connection=db.connection, workspace_loader=loader)
            with TestClient(make_app(services), raise_server_exceptions=False) as client:
                yield Runtime(directory, code, sources, db, client, services, loader,
                              config.account_bindings(), config.secret)
        finally:
            if created:
                # The exact freshly generated name is checked again before DROP.
                monkeypatch.setenv("DEVPLM_DB_NAME", "postgres")
                with db.connection("admin") as admin:
                    admin.autocommit = True
                    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(_checked_database(name))))


def test_real_authentication_and_tenant_isolation(runtime):
    r = runtime
    _safe_status(r.client.get("/v1/projects"), 401)
    response = r.client.post("/v1/auth/token", json={"identifier": "owner", "credential": "explicit-invalid-test-value"})
    _safe_status(response, 401)
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert "explicit-invalid-test-value" not in response.text
    _safe_status(r.client.get("/v1/projects", headers={"Authorization": "Bearer invalid.test.token"}), 401)
    local = {p["id"] for p in r.request("owner", "GET", "/v1/projects")["items"]}
    foreign = {p["id"] for p in r.request("outsider", "GET", "/v1/projects")["items"]}
    assert "dev-plm" in local and foreign == {"event-inbox"} and local.isdisjoint(foreign)
    people = r.request("owner", "GET", "/v1/principals")["items"]
    assert {p["id"] for p in people} == set(ACTORS) - {"outsider"}
    assert all(len(p["roles"]) == 1 for p in people)
    r.request("outsider", "GET", "/v1/projects/dev-plm/requirements", expected=404)
    r.request("owner", "GET", "/v1/principals/outsider/tasks", expected=404)
    discussion = r.discussion()
    r.request("outsider", "GET", "/v1/discussions/" + discussion["id"], expected=404)
    r.request("outsider", "POST", "/v1/projects/dev-plm/discussions",
              {"target_id": r.target, "body": "Unauthorized foreign-tenant body"}, expected=404)


def test_real_git_counts_line_numbers_binary_unknown_and_project_scope(runtime):
    r = runtime
    changes = r.request("owner", "GET", f"/v1/requirements/{r.target}/changes?project_id=dev-plm")["items"]
    change = next(c for c in changes if c["id"] == "CHG-INTEGRATION-FACTS")
    assert len(change["commits"]) == 1 and len(change["commits"][0]) == 40
    diff = r.request("owner", "GET", "/v1/changes/CHG-INTEGRATION-FACTS/diff?project_id=dev-plm")
    assert diff["status"] == "available" and diff["source"] == "git"
    files = {f["path"]: f for f in diff["files"]}
    assert (files["notes.txt"]["added"], files["notes.txt"]["deleted"]) == (2, 1)
    assert files["image.bin"]["added"] is None and files["image.bin"]["deleted"] is None
    hunk = files["notes.txt"]["hunks"][0]
    assert hunk["old_start"] == 1 and hunk["new_start"] == 1
    assert "+changed" in hunk["lines"] and "-keep" in hunk["lines"]
    r.request("owner", "GET", "/v1/changes/CHG-INTEGRATION-FACTS/diff", expected=422)
    r.request("outsider", "GET", "/v1/changes/CHG-INTEGRATION-FACTS/diff?project_id=dev-plm", expected=404)


def test_idempotent_create_replays_one_body_and_rejects_changed_request(runtime):
    r = runtime
    key = "create-" + uuid4().hex
    before_facts = r.facts()
    first = r.discussion(body="Fictional idempotent original", key=key)
    after_first = r.collaboration()
    second = r.discussion(body="Fictional idempotent original", key=key)
    assert first == second and r.count("discussions") == 1
    assert r.collaboration() == after_first
    error = r.request("owner", "POST", "/v1/projects/dev-plm/discussions",
        {"target_id": r.target, "body": "Fictional changed content"}, expected=409, key=key)
    assert error["code"] == "IDEMPOTENCY_CONFLICT"
    assert r.collaboration() == after_first and r.facts() == before_facts
    with r.db.connection() as conn:
        ledger = conn.execute("SELECT * FROM devplm.idempotency_requests WHERE idempotency_key=%s", (key,)).fetchone()
        assert ledger["lifecycle_state"] == "completed" and ledger["response_status"] == 201
        assert ledger["response_body"]["id"] == first["id"] and ledger["last_audit_pk"] is not None


def test_own_discussion_replies_edit_delete_and_conflict_receipts(runtime):
    r = runtime
    d = r.discussion(body="Fictional first-post body must survive")
    dpath = "/v1/discussions/" + d["id"]
    assert r.request("viewer", "GET", dpath)["body"] == d["body"]
    post = r.request("maintainer", "POST", dpath + "/posts", {"body": "Fictional maintainer reply"}, expected=201)
    ppath = "/v1/discussion-posts/" + post["id"]
    for actor in ("owner", "other-owner"):
        r.request(actor, "PATCH", ppath, {"body": "Forbidden edit", "revision": 1}, expected=403)
        r.request(actor, "DELETE", ppath, {"revision": 1}, expected=403)
    r.request("maintainer", "PATCH", dpath, {"body": "Forbidden first-post edit", "revision": 1}, expected=403)
    edited = r.request("maintainer", "PATCH", ppath, {"body": "Fictional revised reply", "revision": 1})
    assert edited["revision"] == 2 and edited["body"] == "Fictional revised reply"
    conflict = r.request("maintainer", "PATCH", ppath, {"body": "Stale editor content", "revision": 1}, expected=409)
    detail = conflict["conflict"]
    assert conflict["code"] == "REVISION_CONFLICT" and detail["current_revision"] == 2
    assert detail["changed_by"]["id"] == "maintainer" and detail["changed_at"]
    assert "body" in detail["changed_fields"]
    assert detail["before"]["body"] == post["body"] and detail["after"]["body"] == edited["body"]
    deleted = r.request("maintainer", "DELETE", ppath, {"revision": 2})
    assert deleted["revision"] == 3 and deleted["deleted_at"] is not None
    assert r.request("owner", "GET", dpath + "/posts")["items"] == []
    first_edit = r.request("owner", "PATCH", dpath, {"body": "Fictional revised first-post", "revision": 1})
    assert first_edit["body"] == "Fictional revised first-post" and first_edit["revision"] == 2
    first_deleted = r.request("owner", "DELETE", dpath, {"revision": 2})
    assert first_deleted["deleted_at"] is not None and first_deleted["revision"] == 3
    r.request("maintainer", "POST", dpath + "/posts", {"body": "Reply after deletion"}, expected=409)


def test_claim_lifecycle_tasks_and_recipient_only_notification_read(runtime):
    r = runtime
    claim = r.claim()
    taskpath = "/v1/principals/maintainer/tasks?project_id=dev-plm"
    assert [c["id"] for c in r.request("owner", "GET", taskpath)["items"]] == [claim["id"]]
    notifications = r.request("maintainer", "GET", "/v1/notifications")["items"]
    assert len(notifications) == 1 and notifications[0]["payload"]["claim_id"] == claim["id"]
    assert r.request("owner", "GET", "/v1/notifications")["items"] == []
    notice = notifications[0]
    npath = "/v1/notifications/" + notice["id"]
    r.request("owner", "PATCH", npath, {"read": True, "revision": notice["revision"]}, expected=403)
    marked = r.request("maintainer", "PATCH", npath, {"read": True, "revision": notice["revision"]})
    assert marked["read_at"] is not None and marked["revision"] == notice["revision"] + 1
    released = r.request("owner", "PATCH", "/v1/claims/" + claim["id"], {"state": "released", "revision": 1})
    assert released["state"] == "released" and released["revision"] == 2
    assert r.request("owner", "GET", taskpath)["items"] == []
    assigned = r.request("maintainer", "PATCH", "/v1/claims/" + claim["id"],
        {"state": "active", "claimant_id": "other-owner", "revision": 2})
    assert assigned["claimant_id"] == "other-owner" and assigned["revision"] == 3
    assert len(r.request("other-owner", "GET", "/v1/notifications")["items"]) == 1
    with r.db.connection() as conn:
        row = conn.execute("SELECT last_audit_pk,revision FROM devplm.claims WHERE pk=%s", (claim["id"],)).fetchone()
        audit = conn.execute("SELECT * FROM devplm.collaboration_audit_events WHERE pk=%s", (row["last_audit_pk"],)).fetchone()
        assert audit["expected_revision"] == 2 and audit["resulting_revision"] == 3
        assert audit["before_value"]["lifecycle_state"] == "released" and audit["after_value"]["lifecycle_state"] == "active"


def test_concurrent_creation_of_one_active_claim_has_one_winner(runtime):
    from fastapi.testclient import TestClient
    r = runtime
    barrier = Barrier(2)
    def create(actor):
        with TestClient(r.client.app, raise_server_exceptions=False) as client:
            barrier.wait(timeout=10)
            response = client.post("/v1/projects/dev-plm/claims",
                headers={"Authorization": "Bearer " + r._tokens[actor], "Idempotency-Key": uuid4().hex},
                json={"target_id": r.target, "claimant_id": actor})
            return response.status_code, response.json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, ("owner", "maintainer")))
    assert sorted(status for status, _ in outcomes) == [201, 409]
    assert r.count("claims") == 1 and r.count("notifications") == 1
    loser = next(body for status, body in outcomes if status == 409)
    assert loser["code"] == "REVISION_CONFLICT" and loser["conflict"]["changed_by"]["id"] in ("owner", "maintainer")


def test_concurrent_revision_compare_and_swap_has_one_winner(runtime):
    from fastapi.testclient import TestClient
    r = runtime
    claim = r.claim()
    barrier = Barrier(2)
    def edit(actor):
        with TestClient(r.client.app, raise_server_exceptions=False) as client:
            barrier.wait(timeout=10)
            response = client.patch("/v1/claims/" + claim["id"],
                headers={"Authorization": "Bearer " + r._tokens[actor], "Idempotency-Key": uuid4().hex},
                json={"state": "released", "revision": 1})
            return response.status_code, response.json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(edit, ("owner", "maintainer")))
    assert sorted(status for status, _ in outcomes) == [200, 409]
    winner = next(body for status, body in outcomes if status == 200)
    loser = next(body for status, body in outcomes if status == 409)
    assert winner["revision"] == 2 and loser["conflict"]["current_revision"] == 2
    assert loser["conflict"]["changed_by"]["id"] == winner["updated_by"]
    assert r.request("owner", "GET", "/v1/claims/" + claim["id"])["revision"] == 2


def test_source_editor_publishes_real_database_and_view(runtime):
    import build
    from backend.source_editor import SourceEditor
    r=runtime
    actor=r.services.authentication.authenticate(r._tokens['owner'])
    editor=SourceEditor(r.services,root=r.code,publish=lambda workspace:build.build(r.code,data_roots=[r.sources]))
    original=editor.read(actor,'dev-plm','requirements/'+r.target+'.md')
    new_id='REQ-FILE-INTEGRATION'
    content=re.sub(r'^id: .+$','id: '+new_id,original['content'],count=1,flags=re.MULTILINE)
    result=editor.save(actor,'dev-plm','requirements/'+new_id+'.md',content,None,'source-integration')
    assert result['state']=='completed'
    requirements=r.request('owner','GET','/v1/projects/dev-plm/requirements')['items']
    assert any(row['id']==new_id for row in requirements)
    assert editor.read(actor,'dev-plm','requirements/'+new_id+'.md')['content']==content
    r.request('owner','POST','/v1/projects/dev-plm/discussions',{'target_id':new_id,'body':'Explicit source editor integration discussion'},expected=201)
    text=(r.code/'site/assets/project-data.js').read_text(encoding='utf-8')
    assert new_id in text


def test_concurrent_same_idempotency_key_replays_one_create(runtime):
    from fastapi.testclient import TestClient
    r = runtime
    barrier, key = Barrier(2), uuid4().hex
    def create(_):
        with TestClient(r.client.app, raise_server_exceptions=False) as client:
            barrier.wait(timeout=10)
            return r.request("owner", "POST", "/v1/projects/dev-plm/discussions",
                {"target_id": r.target, "body": "Fictional simultaneous retry"}, expected=201, key=key, client=client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(create, range(2)))
    assert first == second and r.count("discussions") == 1 and r.count("idempotency_requests") == 1


def test_claim_reassignment_and_creation_acquire_locks_in_one_order(runtime, monkeypatch):
    from fastapi.testclient import TestClient
    r = runtime
    claim = r.claim()
    original_lock = r.services._claim_lock
    creator_locked, editor_ready, worker = Event(), Event(), ContextVar('claim_operation')

    def ordered_lock(conn, target):
        # Deterministic contention with real PostgreSQL locks. An old row-first
        # editor would hold the row while waiting on the creator's target lock.
        if worker.get() == "create":
            original_lock(conn, target)
            creator_locked.set()
            if not editor_ready.wait(10):
                raise RuntimeError("Fixture editor did not reach target lock")
        else:
            editor_ready.set()
            if not creator_locked.wait(10):
                raise RuntimeError("Fixture creator did not acquire target lock")
            original_lock(conn, target)

    monkeypatch.setattr(r.services, "_claim_lock", ordered_lock)

    def invoke(operation):
        worker.set(operation)
        with TestClient(r.client.app, raise_server_exceptions=False) as client:
            if operation == "create":
                return r.request("owner", "POST", "/v1/projects/dev-plm/claims",
                    {"target_id": r.target, "claimant_id": "owner"}, expected=409, client=client)
            return r.request("maintainer", "PATCH", "/v1/claims/" + claim["id"],
                {"state": "active", "claimant_id": "other-owner", "revision": 1}, client=client)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rejected, reassigned = list(pool.map(invoke, ("create", "edit")))
    assert rejected["code"] == "REVISION_CONFLICT"
    assert reassigned["revision"] == 2 and reassigned["claimant_id"] == "other-owner"
    assert r.count("claims") == 1


def test_viewer_denied_all_collaboration_writes_and_error_requests_leave_no_writes(runtime):
    r = runtime
    d, claim = r.discussion(), r.claim()
    before_facts, before_d = r.facts(), r.collaboration()
    requests = [
        ("POST", "/v1/projects/dev-plm/discussions", {"target_id": r.target, "body": "Denied"}),
        ("POST", "/v1/discussions/" + d["id"] + "/posts", {"body": "Denied"}),
        ("PATCH", "/v1/discussions/" + d["id"], {"body": "Denied", "revision": 1}),
        ("DELETE", "/v1/discussions/" + d["id"], {"revision": 1}),
        ("POST", "/v1/projects/dev-plm/claims", {"target_id": r.target, "claimant_id": "viewer"}),
        ("PATCH", "/v1/claims/" + claim["id"], {"state": "released", "revision": 1}),
        ("POST", "/v1/projects/dev-plm/collaboration-exports", {"scope": ["discussions"]}),
        ("POST", "/v1/sync-jobs", {"project_id": "dev-plm", "source_snapshot": r.load()["source_sha256"]}),
    ]
    for method, path, body in requests:
        assert r.request("viewer", method, path, body, expected=403)["code"] == "FORBIDDEN"
    r.request("owner", "POST", "/v1/projects/dev-plm/discussions",
        {"target_id": "NONEXISTENT-TARGET", "body": "Rollback this invalid create"}, expected=404)
    r.request("owner", "POST", "/v1/projects/dev-plm/discussions",
        {"target_id": r.target, "body": "x" * 20001}, expected=422)
    assert r.collaboration() == before_d and r.facts() == before_facts


def test_api_and_raw_database_enforce_single_direction_fact_boundary(runtime):
    from psycopg import sql
    from psycopg.errors import InsufficientPrivilege
    r = runtime
    before = r.facts()
    for path in ("/v1/projects/dev-plm", "/v1/requirements/" + r.target, "/v1/principals/owner"):
        response = r.request("owner", "PATCH", path, {"title": "Forbidden fact mutation"}, expected=405)
        assert response["code"] == "FILE_FACTS_READ_ONLY"
    # PostgreSQL checks privileges even for WHERE false; no tuple is modified.
    with r.db.connection() as conn:
        for table in r.db.F_TABLES:
            for query in ("UPDATE devplm.{} SET updated_at=updated_at WHERE false",
                          "DELETE FROM devplm.{} WHERE false", "INSERT INTO devplm.{} DEFAULT VALUES"):
                with pytest.raises(InsufficientPrivilege):
                    conn.execute(sql.SQL(query).format(sql.Identifier(table)))
                conn.rollback()
    with r.db.connection("sync") as conn:
        for table in r.db.D_TABLES:
            with pytest.raises(InsufficientPrivilege):
                conn.execute(sql.SQL("UPDATE devplm.{} SET updated_at=updated_at WHERE false").format(sql.Identifier(table)))
            conn.rollback()
    assert r.facts() == before


def test_sync_is_idempotent_and_invalid_source_keeps_published_facts(runtime):
    r = runtime
    payload, before = r.load(), r.facts()
    with r.db.connection("sync") as conn:
        receipt = r.db.sync(conn, payload)
    assert receipt["unchanged"] is True and r.facts() == before
    body = {"project_id": "dev-plm", "source_snapshot": payload["source_sha256"]}
    key = uuid4().hex
    job = r.request("owner", "POST", "/v1/sync-jobs", body, expected=202, key=key)
    assert job["state"] == "published" and job["published_snapshot"] == payload["source_sha256"]
    assert r.request("owner", "POST", "/v1/sync-jobs", body, expected=202, key=key) == job
    assert r.request("owner", "GET", "/v1/sync-jobs/" + job["id"])["state"] == "published"
    r.request("maintainer", "POST", "/v1/sync-jobs", body, expected=403)
    r.request("outsider", "GET", "/v1/sync-jobs/" + job["id"], expected=404)
    source = r.sources / "dev-plm/project.yaml"
    original = source.read_bytes()
    try:
        source.write_text("invalid: [unterminated\n", encoding="utf-8")
        failed = r.request("owner", "POST", "/v1/sync-jobs", body, expected=202)
    finally:
        source.write_bytes(original)
    assert failed["state"] == "failed" and failed["published_snapshot"] is None
    assert r.request("owner", "GET", "/v1/sync-jobs/" + failed["id"])["state"] == "failed"
    assert r.facts() == before


def test_sync_published_before_receipt_failure_resumes_same_job_once(runtime, monkeypatch):
    from psycopg import OperationalError
    import yaml
    r = runtime
    before = r.facts()
    path = r.sources / "dev-plm/project.yaml"
    meta = yaml.safe_load(path.read_text(encoding="utf-8"))
    meta["description"] += " Explicit fictional receipt-failure fixture."
    path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    payload = r.load()
    complete, sync = r.db.complete_idempotency, r.db.sync
    calls = {"complete": 0, "sync": 0}
    sentinel = "INVALID_FIXTURE_PASSWORD_SENTINEL_NOT_A_REAL_SECRET"

    def fail_first_receipt(*args, **kwargs):
        calls["complete"] += 1
        if calls["complete"] == 1:
            raise OperationalError("Synthetic connection failure: password=" + sentinel)
        return complete(*args, **kwargs)

    def actual_sync(*args, **kwargs):
        calls["sync"] += 1
        return sync(*args, **kwargs)

    monkeypatch.setattr(r.db, "complete_idempotency", fail_first_receipt)
    monkeypatch.setattr(r.db, "sync", actual_sync)
    key = uuid4().hex
    body = {"project_id": "dev-plm", "source_snapshot": payload["source_sha256"]}
    error = r.request("owner", "POST", "/v1/sync-jobs", body, expected=503, key=key)
    assert error["code"] == "SERVICE_UNAVAILABLE"
    assert sentinel not in json.dumps(error)
    with r.db.connection() as conn:
        jobs = conn.execute("SELECT pk,state,published_snapshot FROM devplm.sync_jobs WHERE idempotency_key=%s", (key,)).fetchall()
    assert len(jobs) == 1 and jobs[0]["state"] == "published"
    assert jobs[0]["published_snapshot"] == payload["source_sha256"]
    published = r.facts()
    assert published != before and calls["sync"] == 1
    retried = r.request("owner", "POST", "/v1/sync-jobs", body, expected=202, key=key)
    assert retried["id"] == str(jobs[0]["pk"]) and retried["state"] == "published"
    assert r.request("owner", "POST", "/v1/sync-jobs", body, expected=202, key=key) == retried
    assert r.count("sync_jobs") == 1 and r.facts() == published
    assert calls == {"complete": 2, "sync": 1}


def test_export_files_published_before_receipt_failure_resume_same_directory(runtime, monkeypatch):
    from psycopg import OperationalError
    r = runtime
    r.discussion()
    complete = r.db.complete_idempotency
    calls = {"complete": 0}
    sentinel = "INVALID_FIXTURE_TOKEN_SENTINEL_NOT_A_REAL_SECRET"

    def fail_first_receipt(*args, **kwargs):
        calls["complete"] += 1
        if calls["complete"] == 1:
            raise OperationalError("Synthetic connection failure: token=" + sentinel)
        return complete(*args, **kwargs)

    monkeypatch.setattr(r.db, "complete_idempotency", fail_first_receipt)
    key, body = uuid4().hex, {"scope": ["discussions", "claims", "audit", "notifications"]}
    before_facts, before_sources = r.facts(), r.load()["source_sha256"]
    error = r.request("owner", "POST", "/v1/projects/dev-plm/collaboration-exports", body, expected=503, key=key)
    assert error["code"] == "EXPORT_FAILED"
    assert sentinel not in json.dumps(error)
    with r.db.connection() as conn:
        jobs = conn.execute("SELECT pk FROM devplm.collaboration_exports WHERE idempotency_key=%s", (key,)).fetchall()
    assert len(jobs) == 1
    export_root = r.sources / "dev-plm/collaboration-exports"
    published = export_root / str(jobs[0]["pk"])
    files = {p.relative_to(published).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in published.rglob("*") if p.is_file()}
    assert "manifest.json" in files and "data.json" in files
    assert r.load()["source_sha256"] == before_sources
    retried = r.request("owner", "POST", "/v1/projects/dev-plm/collaboration-exports", body, expected=202, key=key)
    assert retried["id"] == str(jobs[0]["pk"]) and retried["state"] == "completed"
    assert retried["checksum"] == files["manifest.json"]
    assert r.request("owner", "POST", "/v1/projects/dev-plm/collaboration-exports", body, expected=202, key=key) == retried
    after_files = {p.relative_to(published).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in published.rglob("*") if p.is_file()}
    assert files == after_files and calls["complete"] == 2
    assert [p.name for p in export_root.iterdir() if p.is_dir()] == [published.name]
    assert r.count("collaboration_exports") == 1 and r.facts() == before_facts


def test_removing_a_referenced_fact_rolls_back_the_whole_projection(runtime):
    import yaml
    r = runtime
    r.discussion()
    before, before_d = r.facts(), r.collaboration()
    # Remove only this temporary fixture's project from its explicit data root.
    (r.sources / "dev-plm").rename(r.directory / "removed-project")
    govpath = r.sources / "governance.yaml"
    gov = yaml.safe_load(govpath.read_text(encoding="utf-8"))
    gov["project_tenants"].pop("dev-plm")
    gov.get("project_owners", {}).pop("dev-plm", None)
    govpath.write_text(yaml.safe_dump(gov, allow_unicode=True, sort_keys=False), encoding="utf-8")
    payload = r.load()  # Valid files; rejection must occur at real DB FK boundary.
    with r.db.connection("sync") as conn:
        with pytest.raises(r.db.DatabaseProblem) as failure:
            r.db.sync(conn, payload)
        assert failure.value.code == "SOURCE_DELETION_REQUIRES_TOMBSTONE"
    assert r.facts() == before and r.collaboration() == before_d


def test_export_is_recoverable_offline_data_and_never_a_fact_sync_input(runtime):
    import build
    from backend.exports import restore
    from backend.manage import provision_logins
    r = runtime
    body = "Explicit fictional collaboration content for offline recovery"
    d = r.discussion(body=body)
    claim = r.claim()
    before_workspace, before_facts = r.load(), r.facts()
    job = r.request("owner", "POST", "/v1/projects/dev-plm/collaboration-exports",
        {"scope": ["discussions", "claims", "audit", "notifications"]}, expected=202)
    assert job["state"] == "completed" and job["manifest_path"] and job["checksum"]
    assert r.request("owner", "GET", "/v1/collaboration-exports/" + job["id"]) == job
    r.request("outsider", "GET", "/v1/collaboration-exports/" + job["id"], expected=404)
    workspace = r.load()
    assert workspace["source_sha256"] == before_workspace["source_sha256"]
    assert workspace["documents"] == before_workspace["documents"]
    assert workspace["export_documents"] and "dev-plm" in workspace["collaboration_exports"]
    snapshot = workspace["collaboration_exports"]["dev-plm"]
    assert set(snapshot["tables"]) <= set(r.db.D_TABLES)
    assert all("collaboration-exports" not in key for key in workspace["documents"])
    before_d = r.collaboration()
    with r.db.connection("sync") as conn:
        assert r.db.sync(conn, workspace)["unchanged"] is True
    assert r.facts() == before_facts and r.collaboration() == before_d
    build.build(r.code, data_roots=[r.sources])
    generated = r.code / "site/assets/project-data.js"
    offline = json.loads(generated.read_text(encoding="utf-8").split("window.DEVPLM_DATA = ", 1)[1].strip().removesuffix(";"))
    project = next(p for p in offline["projects"] if p["id"] == "dev-plm")
    assert project["collaboration"]["manifest"]["authority"] == "database-export"
    assert body in json.dumps(project["collaboration"], ensure_ascii=False)
    # Destroy/rebuild only this test's isolated schema, then restore actual D files.
    with r.db.connection("admin") as conn:
        assert r.db.migrate(conn, "down")["changed"] is True
        assert r.db.migrate(conn, "up")["changed"] is True
        assert r.db.migrate(conn, "up")["changed"] is False
        provision_logins(conn)
    with r.db.connection("sync") as conn:
        r.db.sync(conn, workspace)
    assert r.facts() == before_facts and r.count("discussions") == 0
    with r.db.connection("admin") as conn:
        restore(conn, snapshot)
    recovered = r.request("owner", "GET", "/v1/discussions/" + d["id"])
    assert recovered["body"] == body and recovered["revision"] == d["revision"]
    assert r.request("owner", "GET", "/v1/claims/" + claim["id"])["claimant_id"] == "maintainer"
    assert len(r.request("maintainer", "GET", "/v1/notifications")["items"]) == 1
    # Corrupt a copy's export: validation must preserve the previous offline site.
    original_site = generated.read_bytes()
    export_root = r.sources / "dev-plm/collaboration-exports" / job["id"]
    data_path = export_root / "data.json"
    original = data_path.read_bytes()
    try:
        data_path.write_bytes(original + b"\n")
        with pytest.raises(build.BuildError):
            build.build(r.code, data_roots=[r.sources])
    finally:
        data_path.write_bytes(original)
    assert generated.read_bytes() == original_site
