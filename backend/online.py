"""Same-origin browser workspace; cookie bridge leaves /v1 bearer-only."""
import json
from pathlib import Path
from fastapi import Request, Header
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from .config import ROOT
from .protocol import ServiceError
from .source_editor import SourceEditor

class SourceWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    path:str
    content:str=Field(min_length=1,max_length=1000000)
    revision:str|None

def install_online(app,auth,services):
    editor=SourceEditor(services);app.state.source_editor=editor
    def actor(request):return auth.authenticate(request.cookies.get('devplm_session',''))

    @app.get('/workbench',include_in_schema=False)
    def workbench():return FileResponse(ROOT/'backend/web/index.html',headers={'Content-Type':'text/html; charset=utf-8'})

    @app.get('/private/assets/{name}',include_in_schema=False)
    def asset(name:str):
        if name not in {'online.js','online.css'}:raise ServiceError(404,'NOT_FOUND','资源不存在。')
        return FileResponse(ROOT/'backend/web'/name)

    @app.get('/private/workspace',tags=['网页工作区'])
    def workspace(request:Request):
        identity=actor(request)
        from .external_logs import catalog
        return {'actor':{'id':identity.principal_id,'role':identity.role},
            'projects':[p for p in services.list_projects(identity) if not p['example']]+catalog(identity)}

    @app.get('/private/projects/{project_id}/files',tags=['网页工作区'])
    def files(project_id:str,request:Request):return {'items':editor.files(actor(request),project_id)}

    @app.get('/private/projects/{project_id}/logs',tags=['网页工作区'])
    def logs(project_id:str,request:Request,revision:str|None=None):
        from .live_logs import read_logs
        from .external_logs import catalog,read
        identity=actor(request)
        if any(p['id']==project_id for p in catalog(identity)):
            return read(identity,project_id,revision)
        return read_logs(editor,identity,project_id,revision)

    @app.get('/private/projects/{project_id}/logs/{record_key}',tags=['网页工作区'])
    def log_detail(project_id:str,record_key:str,request:Request):
        from .external_logs import detail
        return detail(actor(request),project_id,record_key)

    @app.get('/private/projects/{project_id}/sections/{section_id}',tags=['网页工作区'])
    def project_section(project_id:str,section_id:str,request:Request):
        from .project_documents import section
        return section(actor(request),project_id,section_id)

    @app.get('/private/projects/{project_id}/documents/{document_key}',tags=['网页工作区'])
    def project_document(project_id:str,document_key:str,request:Request,revision:str|None=None):
        from .project_documents import document
        return document(actor(request),project_id,document_key,revision)

    @app.get('/private/projects/{project_id}/source',tags=['网页工作区'])
    def read_source(project_id:str,path:str,request:Request):return editor.read(actor(request),project_id,path)

    @app.put('/private/projects/{project_id}/source',tags=['网页工作区'])
    def write_source(project_id:str,body:SourceWrite,request:Request,idempotency_key:str=Header(alias='Idempotency-Key')):
        row=editor.save(actor(request),project_id,body.path,body.content,body.revision,idempotency_key)
        return {k:row[k] for k in ['id','path','state','after','message','updated_at']}

    @app.get('/private/projects/{project_id}/history',tags=['网页工作区'])
    def history(project_id:str,request:Request):return {'items':editor.history(actor(request),project_id)}

    @app.get('/private/operations',tags=['网页工作区'])
    def operations(request:Request):
        identity=actor(request)
        if identity.role!='owner':raise ServiceError(403,'FORBIDDEN','仅维护者查看运维状态。')
        receipt=ROOT/'.local/maintenance-status.json'
        return json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {'state':'not_configured','message':'自动维护尚未配置。'}

    @app.get('/site/index.html',include_in_schema=False)
    def private_index():
        text=(ROOT/'site/index.html').read_text(encoding='utf-8')
        # Explicit link only. Offline/public HTML never gains network behavior.
        text=text.replace('</body>','<a href="/workbench" style="position:fixed;right:20px;bottom:20px;z-index:200;background:#3458ef;color:white;padding:12px 20px;border-radius:8px;text-decoration:none">在线编辑与协作</a></body>')
        return HTMLResponse(text)

    @app.get('/site/assets/project-data.js',include_in_schema=False)
    def private_project_data(request:Request):
        allowed={p['id'] for p in services.list_projects(actor(request))}
        raw=(ROOT/'site/assets/project-data.js').read_text(encoding='utf-8')
        payload=json.loads(raw.split('window.DEVPLM_DATA = ',1)[1].strip().removesuffix(';'))
        payload['projects']=[p for p in payload['projects'] if p['id'] in allowed]
        data=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
        return Response('window.DEVPLM_DATA = '+data+';',media_type='application/javascript')
