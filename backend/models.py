"""Explicit reviewed-by-code models; never constructed from OpenAPI JSON."""
from datetime import datetime
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field

NonEmpty = Annotated[str, Field(min_length=1)]
Revision = Annotated[int, Field(ge=1)]
NonNegative = Annotated[int, Field(ge=0)]
PostBody = Annotated[str, Field(min_length=1, max_length=20000)]
CommitSHA = Annotated[str, Field(pattern="^[0-9a-f]{40,64}$")]
Role = Literal["owner", "maintainer", "viewer"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Actor(Model):
    id: str
    display_name: str


class Conflict(Model):
    current_revision: Revision
    changed_by: Actor
    changed_at: datetime
    changed_fields: list[str]
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class Error(Model):
    code: Literal["AUTH_REQUIRED", "INVALID_CREDENTIALS", "FORBIDDEN", "NOT_FOUND",
                  "REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "VALIDATION_ERROR",
                  "SOURCE_VALIDATION_FAILED", "EXPORT_FAILED", "FILE_FACTS_READ_ONLY",
                  "SERVICE_UNAVAILABLE"]
    message: str
    request_id: str
    conflict: Conflict | None = None


class TokenRequest(Model):
    identifier: NonEmpty
    credential: Annotated[str, Field(min_length=1, repr=False, json_schema_extra={"writeOnly": True})]


class AccessToken(Model):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: Annotated[int, Field(ge=1)]


class Project(Model):
    id: str
    name: str
    type: Literal["software", "agent", "aigc"]
    example: bool
    stage: str
    source_path: str


class Requirement(Model):
    id: str
    title: str
    original: str
    status: str
    source_path: str


class Change(Model):
    id: str
    title: str
    requirements: list[str]
    commits: list[CommitSHA]
    narrative: str
    source_path: str


class DiffHunk(Model):
    old_start: NonNegative
    old_count: NonNegative
    new_start: NonNegative
    new_count: NonNegative
    lines: list[str]


class DiffFile(Model):
    path: str
    added: NonNegative | None
    deleted: NonNegative | None
    hunks: list[DiffHunk]


class ChangeDiff(Model):
    change_id: str
    status: Literal["available", "partial", "unavailable", "no_history"]
    source: Literal["git"]
    files: list[DiffFile]
    notice: str


class SyncRequest(Model):
    project_id: str
    source_snapshot: str


class SyncJob(Model):
    id: str
    state: Literal["queued", "validating", "staging", "published", "failed"]
    source_snapshot: str
    published_snapshot: str | None
    message: str


class CreateDiscussion(Model):
    target_id: str
    body: PostBody


class RevisionRequest(Model):
    revision: Revision


class EditBody(RevisionRequest):
    body: PostBody


class CreatePost(Model):
    body: PostBody
    parent_post_id: str | None = None


class Discussion(Model):
    id: str
    project_id: str
    target_id: str
    body: str
    revision: Revision
    authority: Literal["database"]
    export_status: Literal["not_exported", "exported"]
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    deleted_at: datetime | None


class DiscussionPost(Model):
    id: str
    project_id: str
    discussion_id: str
    parent_post_id: str | None
    body: str
    revision: Revision
    authority: Literal["database"]
    export_status: Literal["not_exported", "exported"]
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    deleted_at: datetime | None


class CreateClaim(Model):
    target_id: NonEmpty
    claimant_id: NonEmpty


class UpdateClaim(Model):
    state: Literal["active", "released"]
    revision: Revision
    claimant_id: NonEmpty | None = None


class Claim(Model):
    id: str
    project_id: str
    target_id: str
    claimant_id: str
    state: Literal["active", "released", "expired"]
    revision: Revision
    authority: Literal["database"]
    updated_by: str
    updated_at: datetime


class ExportRequest(Model):
    scope: Annotated[set[Literal["discussions", "claims", "audit", "notifications"]], Field(min_length=1)]


class ExportJob(Model):
    id: str
    state: Literal["queued", "running", "completed", "failed"]
    manifest_path: str | None
    checksum: str | None
    message: str


class Principal(Model):
    id: str
    display_name: str
    actor_type: Literal["human", "agent", "service"]
    roles: list[Role]


class Notification(Model):
    id: str
    project_id: str
    recipient_id: str
    payload: dict[str, Any]
    created_at: datetime
    read_at: datetime | None
    revision: Revision


class MarkRead(Model):
    read: Literal[True]
    revision: Revision


class Projects(Model):
    items: list[Project]


class Requirements(Model):
    items: list[Requirement]


class Changes(Model):
    items: list[Change]


class Principals(Model):
    items: list[Principal]


class Discussions(Model):
    items: list[Discussion]


class DiscussionPosts(Model):
    items: list[DiscussionPost]


class Claims(Model):
    items: list[Claim]


class Notifications(Model):
    items: list[Notification]
