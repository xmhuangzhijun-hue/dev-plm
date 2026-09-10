"""Local API entry point; errors deliberately omit request bodies and secrets."""
import json
from fastapi.responses import JSONResponse
from fastapi.exceptions import ResponseValidationError
from .config import ROOT, ConfigurationError, settings
from . import db
from .auth import Authentication
from .protocol import ServiceError
from .routes import create_app
from .services import Services


def make_app(services=None,authentication=None):
    if services is None:
        import os
        from build import load_workspace
        roots=settings().get('DEVPLM_DATA_ROOTS')
        services=Services(workspace_loader=lambda:load_workspace(ROOT,data_roots=roots.split(os.pathsep) if roots else None))
        from tools.workspace_sources import resolve_data_roots
        services.source_roots=resolve_data_roots(ROOT,roots.split(os.pathsep) if roots else None)
    auth=authentication or Authentication(services.resolve_identity)
    services.authentication=auth
    documentation=json.loads((ROOT/'projects/dev-plm/api/openapi.json').read_text(encoding='utf-8'))
    app=create_app(services,auth.authenticate,documentation)
    app.state.services=services

    async def driver_error(request,exc):
        return JSONResponse(status_code=503,content={'code':'SERVICE_UNAVAILABLE',
            'message':'数据库操作未完成；使用原幂等键核对或接续。','request_id':request.state.request_id})
    try:
        import psycopg
        app.add_exception_handler(psycopg.Error,driver_error)
    except ImportError:
        pass  # Schema inspection remains available before environment preparation.

    from build import BuildError
    @app.exception_handler(BuildError)
    async def source_error(request,exc):
        return JSONResponse(status_code=503,content={'code':'SOURCE_VALIDATION_FAILED',
            'message':str(exc),'request_id':request.state.request_id})

    @app.exception_handler(db.DatabaseProblem)
    async def database_error(request,exc):
        code={'SOURCE_DELETION_REQUIRES_TOMBSTONE':'SOURCE_VALIDATION_FAILED','REQUEST_IN_PROGRESS':'IDEMPOTENCY_CONFLICT'}.get(exc.code,exc.code)
        if code.startswith('DATABASE_') or code=='MIGRATION_CHANGED':code='SERVICE_UNAVAILABLE'
        status=503 if code=='SERVICE_UNAVAILABLE' else exc.status
        return JSONResponse(status_code=status,content={'code':code,'message':exc.message,'request_id':request.state.request_id})

    @app.exception_handler(ConfigurationError)
    async def config_error(request,exc):
        return JSONResponse(status_code=503,content={'code':'SERVICE_UNAVAILABLE','message':'本机配置尚未就绪。','request_id':request.state.request_id})

    @app.exception_handler(ResponseValidationError)
    async def response_error(request,exc):
        return JSONResponse(status_code=503,content={'code':'SERVICE_UNAVAILABLE','message':'响应未通过契约校验，请查看本机验收报告。','request_id':request.state.request_id})
    return app


app=make_app()
