"""Explicit FastAPI routes. app.openapi remains FastAPI's own implementation."""
from typing import Annotated, Callable
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import models as m
from .protocol import Identity, ServiceError, Services

Identifier = Annotated[str, Path(min_length=1)]
ProjectScope = Annotated[str, Query(min_length=1)]
OptionalFilter = Annotated[str | None, Query(min_length=1)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]

READ_ONLY_PATHS = tuple(re.compile(pattern) for pattern in (
    r"^/v1/projects(?:/[^/]+)?$",
    r"^/v1/projects/[^/]+/requirements(?:/[^/]+)?$",
    r"^/v1/requirements(?:/[^/]+(?:/changes)?)?$",
    r"^/v1/changes(?:/[^/]+(?:/diff)?)?$",
    r"^/v1/principals(?:/[^/]+(?:/tasks)?)?$",
))


def error_responses(*codes):
    # Every operation uses configured authentication and/or persistent services.
    # Configuration, driver and response-validation failures share a safe 503.
    return {code: {"model": m.Error, "description": "明确错误码与请求回执"} for code in (*codes, 503)}


def _payload(body):
    result = body.model_dump(mode="json", exclude_none=True)
    if isinstance(body, m.ExportRequest):
        result["scope"] = sorted(body.scope)
    return result


def create_app(services: Services, authenticate: Callable[[str], Identity], documentation: dict | None = None) -> FastAPI:
    app = FastAPI(title="dev-plm 在线协作 API", version="0.2.0", openapi_version="3.1.0")
    bearer = HTTPBearer(scheme_name="bearerAuth", auto_error=False,
                        description="短期访问令牌；租户与角色从已验证身份获得。")

    def identity(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Identity:
        if credentials is None:
            raise ServiceError(401, "AUTH_REQUIRED", "没有有效访问令牌。")
        actor = authenticate(credentials.credentials)
        if not isinstance(actor, Identity) or actor.role not in ("owner", "maintainer", "viewer"):
            raise ServiceError(401, "AUTH_REQUIRED", "没有有效访问令牌。")
        return actor

    def writer(actor: Annotated[Identity, Depends(identity)]) -> Identity:
        if actor.role == "viewer":
            raise ServiceError(403, "FORBIDDEN", "viewer 只能读取，不能修改协作数据。")
        return actor

    def own_statement(actor, existing):
        if existing["created_by"] != actor.principal_id:
            raise ServiceError(403, "FORBIDDEN", "只能编辑或删除自己的发言。")

    Auth = Annotated[Identity, Depends(identity)]
    WriteAuth = Annotated[Identity, Depends(writer)]
    read_errors = error_responses(401, 404, 422)
    write_errors = error_responses(401, 403, 404, 409, 422)
    collaboration = {"tags": ["协作数据"], "openapi_extra": {"x-requirements": ["DEV-REQ-011", "DEV-REQ-012"]}}
    facts = {"tags": ["项目事实"], "openapi_extra": {"x-requirements": ["DEV-REQ-011", "DEV-REQ-012"]}}

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = "REQ-" + uuid4().hex
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and any(pattern.fullmatch(request.url.path) for pattern in READ_ONLY_PATHS):
            return JSONResponse(status_code=405, content={"code": "FILE_FACTS_READ_ONLY",
                "message": "F/G 项目事实只能先修改来源文件，再由同步器单向写入。",
                "request_id": request.state.request_id}, headers={"Allow": "GET"})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        result = m.Error(code=exc.code, message=exc.message, request_id=request.state.request_id,
                         conflict=exc.conflict)
        return JSONResponse(status_code=exc.status, content=result.model_dump(mode="json",
            exclude={"conflict"} if exc.conflict is None else set()))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo validation input: auth bodies may contain credentials.
        return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR",
            "message": "输入不符合契约，请核对字段、路径和必填请求头。", "request_id": request.state.request_id})

    @app.post("/v1/auth/token", operation_id="issueAccessToken", response_model=m.AccessToken,
              responses=error_responses(401, 422), tags=["身份认证"], summary="取得在线协作访问令牌")
    def issue_token(body: m.TokenRequest):
        return services.issue_token(body.identifier, body.credential)

    @app.get("/v1/projects", operation_id="listProjects", response_model=m.Projects,
             responses=error_responses(401, 404), summary="读取项目", **facts)
    def list_projects(actor: Auth):
        return {"items": services.list_projects(actor)}

    @app.get("/v1/projects/{project_id}/requirements", operation_id="listRequirements", response_model=m.Requirements,
             responses=read_errors, summary="读取项目需求", **facts)
    def list_requirements(project_id: Identifier, actor: Auth):
        return {"items": services.list_requirements(actor, project_id)}

    @app.get("/v1/requirements/{requirement_id}/changes", operation_id="listRequirementChanges", response_model=m.Changes,
             responses=read_errors, summary="读取需求关联变更", **facts)
    def list_changes(requirement_id: Identifier, project_id: ProjectScope, actor: Auth):
        return {"items": services.list_requirement_changes(actor, project_id, requirement_id)}

    @app.get("/v1/changes/{change_id}/diff", operation_id="getChangeDiff", response_model=m.ChangeDiff,
             responses=read_errors, summary="读取 Git 客观差异", **facts)
    def change_diff(change_id: Identifier, project_id: ProjectScope, actor: Auth):
        return services.get_change_diff(actor, project_id, change_id)

    @app.post("/v1/sync-jobs", operation_id="startProjection", response_model=m.SyncJob, status_code=202,
              responses=write_errors, tags=["文件同步"], summary="启动文件投影同步")
    def start_sync(body: m.SyncRequest, request: Request, actor: WriteAuth, key: IdempotencyKey):
        return services.start_sync(actor, _payload(body), key, request.state.request_id)

    @app.get("/v1/sync-jobs/{job_id}", operation_id="getProjection", response_model=m.SyncJob,
             responses=read_errors, tags=["文件同步"], summary="读取同步状态")
    def get_sync(job_id: Identifier, actor: Auth):
        return services.get_sync(actor, job_id)

    @app.post("/v1/projects/{project_id}/discussions", operation_id="createDiscussion", response_model=m.Discussion,
              status_code=201, responses=write_errors, summary="创建含首帖正文的讨论", **collaboration)
    def create_discussion(project_id: Identifier, body: m.CreateDiscussion, request: Request, actor: WriteAuth, key: IdempotencyKey):
        return services.create_discussion(actor, project_id, _payload(body), key, request.state.request_id)

    @app.get("/v1/projects/{project_id}/discussions", operation_id="listDiscussions", response_model=m.Discussions,
             responses=read_errors, summary="读取项目讨论", **collaboration)
    def list_discussions(project_id: Identifier, actor: Auth, target_id: OptionalFilter = None):
        return {"items": services.list_discussions(actor, project_id, target_id)}

    @app.get("/v1/discussions/{discussion_id}", operation_id="getDiscussion", response_model=m.Discussion,
             responses=read_errors, summary="读取讨论首帖", **collaboration)
    def get_discussion(discussion_id: Identifier, actor: Auth):
        return services.get_discussion(actor, discussion_id)

    @app.patch("/v1/discussions/{discussion_id}", operation_id="updateDiscussion", response_model=m.Discussion,
               responses=write_errors, summary="编辑本人讨论首帖", **collaboration)
    def update_discussion(discussion_id: Identifier, body: m.EditBody, request: Request, actor: WriteAuth, key: IdempotencyKey):
        own_statement(actor, services.get_discussion(actor, discussion_id))
        return services.update_discussion(actor, discussion_id, _payload(body), key, request.state.request_id)

    @app.delete("/v1/discussions/{discussion_id}", operation_id="deleteDiscussion", response_model=m.Discussion,
                responses=write_errors, summary="删除本人讨论首帖并保留墓碑", **collaboration)
    def delete_discussion(discussion_id: Identifier, body: m.RevisionRequest, request: Request, actor: WriteAuth, key: IdempotencyKey):
        own_statement(actor, services.get_discussion(actor, discussion_id))
        return services.delete_discussion(actor, discussion_id, _payload(body), key, request.state.request_id)

    @app.get("/v1/discussions/{discussion_id}/posts", operation_id="listDiscussionPosts", response_model=m.DiscussionPosts,
             responses=read_errors, summary="读取讨论回复", **collaboration)
    def list_posts(discussion_id: Identifier, actor: Auth):
        return {"items": services.list_posts(actor, discussion_id)}

    @app.post("/v1/discussions/{discussion_id}/posts", operation_id="createDiscussionPost", response_model=m.DiscussionPost,
              status_code=201, responses=write_errors, summary="回复讨论", **collaboration)
    def create_post(discussion_id: Identifier, body: m.CreatePost, request: Request, actor: WriteAuth, key: IdempotencyKey):
        return services.create_post(actor, discussion_id, _payload(body), key, request.state.request_id)

    @app.patch("/v1/discussion-posts/{post_id}", operation_id="updateDiscussionPost", response_model=m.DiscussionPost,
               responses=write_errors, summary="编辑本人回复", **collaboration)
    def update_post(post_id: Identifier, body: m.EditBody, request: Request, actor: WriteAuth, key: IdempotencyKey):
        own_statement(actor, services.get_post(actor, post_id))
        return services.update_post(actor, post_id, _payload(body), key, request.state.request_id)

    @app.delete("/v1/discussion-posts/{post_id}", operation_id="deleteDiscussionPost", response_model=m.DiscussionPost,
                responses=write_errors, summary="删除本人回复并保留墓碑", **collaboration)
    def delete_post(post_id: Identifier, body: m.RevisionRequest, request: Request, actor: WriteAuth, key: IdempotencyKey):
        own_statement(actor, services.get_post(actor, post_id))
        return services.delete_post(actor, post_id, _payload(body), key, request.state.request_id)

    @app.get("/v1/projects/{project_id}/claims", operation_id="listClaims", response_model=m.Claims,
             responses=read_errors, summary="读取项目认领", **collaboration)
    def list_claims(project_id: Identifier, actor: Auth, state: Annotated[str | None, Query(pattern="^(active|released|expired)$")] = None):
        return {"items": services.list_claims(actor, project_id, state)}

    @app.post("/v1/projects/{project_id}/claims", operation_id="createClaim", response_model=m.Claim,
              status_code=201, responses=write_errors, summary="向已登记主体指派处理对象", **collaboration)
    def create_claim(project_id: Identifier, body: m.CreateClaim, request: Request, actor: WriteAuth, key: IdempotencyKey):
        return services.create_claim(actor, project_id, _payload(body), key, request.state.request_id)

    @app.get("/v1/claims/{claim_id}", operation_id="getClaim", response_model=m.Claim,
             responses=read_errors, summary="读取认领", **collaboration)
    def get_claim(claim_id: Identifier, actor: Auth):
        return services.get_claim(actor, claim_id)

    @app.patch("/v1/claims/{claim_id}", operation_id="updateClaim", response_model=m.Claim,
               responses=write_errors, summary="释放或重新指派认领", **collaboration)
    def update_claim(claim_id: Identifier, body: m.UpdateClaim, request: Request, actor: WriteAuth, key: IdempotencyKey):
        return services.update_claim(actor, claim_id, _payload(body), key, request.state.request_id)

    @app.get("/v1/principals", operation_id="listPrincipals", response_model=m.Principals,
             responses=error_responses(401, 404), summary="读取同租户登记主体", **facts)
    def list_principals(actor: Auth):
        return {"items": services.list_principals(actor)}

    @app.get("/v1/principals/{principal_id}/tasks", operation_id="listPrincipalTasks", response_model=m.Claims,
             responses=read_errors, summary="读取某人当前 active 认领", **collaboration)
    def list_tasks(principal_id: Identifier, actor: Auth, project_id: OptionalFilter = None):
        return {"items": services.list_tasks(actor, principal_id, project_id)}

    @app.get("/v1/notifications", operation_id="listNotifications", response_model=m.Notifications,
             responses=error_responses(401, 404), summary="读取本人通知", **collaboration)
    def list_notifications(actor: Auth):
        return {"items": services.list_notifications(actor)}

    @app.patch("/v1/notifications/{notification_id}", operation_id="markNotificationRead", response_model=m.Notification,
               responses=write_errors, summary="将本人通知标记已读", **collaboration)
    def mark_read(notification_id: Identifier, body: m.MarkRead, request: Request, actor: WriteAuth, key: IdempotencyKey):
        notification = services.get_notification(actor, notification_id)
        if notification["recipient_id"] != actor.principal_id:
            raise ServiceError(403, "FORBIDDEN", "只能修改本人通知的阅读状态。")
        return services.update_notification(actor, notification_id, _payload(body), key, request.state.request_id)

    @app.post("/v1/projects/{project_id}/collaboration-exports", operation_id="exportCollaboration", response_model=m.ExportJob,
              status_code=202, responses=write_errors, summary="导出协作数据为普通文件", **collaboration)
    def create_export(project_id: Identifier, body: m.ExportRequest, request: Request, actor: WriteAuth, key: IdempotencyKey):
        return services.create_export(actor, project_id, _payload(body), key, request.state.request_id)

    @app.get("/v1/collaboration-exports/{export_id}", operation_id="getCollaborationExport", response_model=m.ExportJob,
             responses=read_errors, summary="读取协作导出回执", **collaboration)
    def get_export(export_id: Identifier, actor: Auth):
        return services.get_export(actor, export_id)

    if documentation is not None:
        from .documentation import apply_documentation
        apply_documentation(app, documentation)
    return app
