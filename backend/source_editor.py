"""Private, authorized source-file editing with compare-before-write receipts.

Database facts still enter through the existing source synchronizer. No source
file or collaboration table is silently substituted by a browser-side draft.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import tempfile
from uuid import uuid4

from .config import ROOT
from .protocol import ServiceError

EDITABLE_DIRS={'requirements','ui','data','api','records','tests','prompts','design','releases','incidents','audits','reviews'}
EDITABLE_FILES={'onboarding.yaml','profile.yaml'}

def sha(data):return hashlib.sha256(data).hexdigest()
def timestamp():return datetime.now(timezone.utc).isoformat()

def atomic(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.edit-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()

@contextmanager
def workspace_lock(root=ROOT):
    path=Path(root)/'.local/workspace.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise ServiceError(409,'REVISION_CONFLICT','另一个保存或备份正在进行，请稍后使用原操作重试。') from None
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)

def editable(name):
    path=PurePosixPath(name)
    return bool(name and '\\' not in name and ':' not in name and not path.is_absolute()
        and all(part not in {'.','..'} and not part.startswith('.') for part in path.parts)
        and path.suffix.lower() in {'.md','.yaml','.yml','.json'}
        and (name in EDITABLE_FILES or path.parts[0] in EDITABLE_DIRS))

def recover_prepared(root,environment):
    """Interrupted, unacknowledged saves roll back only their exact written bytes.

    Called under workspace_lock before full source synchronization on recovery.
    Concurrent edits are preserved and require an explicit operator review.
    """
    roots=[Path(p).resolve() for p in environment.get('DEVPLM_DATA_ROOTS','').split(os.pathsep) if p] or [Path(root)/'projects']
    changed=False
    for receipt in (Path(root)/'.local/edits').glob('*/receipt.json'):
        row=json.loads(receipt.read_text(encoding='utf-8'))
        if row['state'] in {'sync_pending','published','view_pending'}:changed=True
        if row['state']!='prepared':continue
        changed=True
        project_id=row['project_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',project_id) or not editable(row['path']):raise RuntimeError('Invalid pending edit receipt')
        directories=[r/project_id for r in roots if (r/project_id).is_dir()]
        if len(directories)!=1:raise RuntimeError('Pending edit project cannot be resolved')
        directory=directories[0].resolve();path=(directory/row['path']).resolve()
        if not path.is_relative_to(directory):raise RuntimeError('Pending edit path escaped project')
        current=sha(path.read_bytes()) if path.is_file() else None
        if current==row['after']:
            before=receipt.parent/'before.bin'
            if row['before'] is None:path.unlink()
            elif before.is_file() and sha(before.read_bytes())==row['before']:atomic(path,before.read_bytes())
            else:raise RuntimeError('Pending edit backup unavailable')
        elif current!=row['before']:raise RuntimeError('Concurrent source change requires review')
        row.update(state='rolled_back',updated_at=timestamp(),message='服务恢复时撤回了未完成的保存；修改内容仍保留在操作备份。')
        atomic(receipt,json.dumps(row,ensure_ascii=False).encode())
    return changed

class SourceEditor:
    def __init__(self,services,root=ROOT,publish=None):
        self.services=services;self.root=Path(root);self._scope_workspace=None
        if publish is None:
            from build import build
            publish=lambda workspace:build(self.root,data_roots=workspace['data_roots'],validated_workspace=workspace)
        self.publish=publish

    def scope(self,actor,project_id):
        allowed={p['id'] for p in self.services.list_projects(actor) if not p['example']}
        if project_id not in allowed:raise ServiceError(404,'NOT_FOUND','项目不存在或当前账号没有权限。')
        roots=getattr(self.services,'source_roots',None)
        if roots:
            directories=[r/project_id for r in roots if (r/project_id).is_dir() and (r/project_id).resolve().is_relative_to(r)]
            if len(directories)!=1:raise ServiceError(404,'NOT_FOUND','项目资料根缺失或重复。')
            directory=directories[0].resolve()
            return {'data_roots':roots,'project_directories':{project_id:directory}},directory
        if self._scope_workspace is None or project_id not in self._scope_workspace['project_directories']:
            loaded=self.services.workspace_loader()
            self._scope_workspace={key:loaded[key] for key in ['project_directories','data_roots']}
        workspace=self._scope_workspace
        return workspace,workspace['project_directories'][project_id]

    def path(self,directory,name,create=False):
        if not editable(name):raise ServiceError(403,'FORBIDDEN','该文件不支持网页编辑。')
        path=directory.joinpath(*PurePosixPath(name).parts)
        if not path.resolve().is_relative_to(directory.resolve()):raise ServiceError(403,'FORBIDDEN','文件超出项目目录。')
        current=path
        while current!=directory:
            if current.is_symlink():raise ServiceError(403,'FORBIDDEN','网页不编辑链接文件。')
            current=current.parent
        if not create and not path.is_file():raise ServiceError(404,'NOT_FOUND','文件不存在。')
        return path

    def files(self,actor,project_id):
        _,directory=self.scope(actor,project_id)
        return [{'path':p.relative_to(directory).as_posix(),'bytes':p.stat().st_size}
            for p in sorted(directory.rglob('*')) if p.is_file() and editable(p.relative_to(directory).as_posix()) and not p.is_symlink()]

    def read(self,actor,project_id,name):
        _,directory=self.scope(actor,project_id);path=self.path(directory,name)
        data=path.read_bytes()
        if len(data)>1000000:raise ServiceError(422,'VALIDATION_ERROR','文件过大，请在本机编辑。')
        return {'path':name,'content':data.decode('utf-8-sig'),'revision':sha(data)}

    def history(self,actor,project_id):
        self.scope(actor,project_id);items=[]
        for path in (self.root/'.local/edits').glob('*/receipt.json'):
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['tenant_id']==actor.tenant_id and row['project_id']==project_id:
                items.append({k:row.get(k) for k in ['id','path','actor','created_at','updated_at','state','before','after','message']})
        return sorted(items,key=lambda row:row['created_at'],reverse=True)[:100]

    def save(self,actor,project_id,name,content,revision,key):
        if actor.role!='owner':raise ServiceError(403,'FORBIDDEN','只有维护者账号可以保存并发布项目文件。')
        if not key or len(key)>200:raise ServiceError(422,'VALIDATION_ERROR','缺少有效操作编号。')
        data=content.encode('utf-8')
        if not data or len(data)>1000000:raise ServiceError(422,'VALIDATION_ERROR','内容须为1至1000000字节。')
        operation=sha((actor.tenant_id+'\0'+actor.principal_id+'\0'+key).encode())
        fingerprint=sha(json.dumps([project_id,name,content,revision],ensure_ascii=False).encode())
        folder=self.root/'.local/edits'/operation;receipt=folder/'receipt.json'
        with workspace_lock(self.root):
            workspace,directory=self.scope(actor,project_id)
            path=self.path(directory,name,create=revision is None)
            if receipt.exists():
                row=json.loads(receipt.read_text(encoding='utf-8'))
                if row['fingerprint']!=fingerprint:raise ServiceError(409,'IDEMPOTENCY_CONFLICT','该操作编号已经用于另一份内容。')
                if row['state']=='completed':return row
                if row['state']=='sync_pending':
                    if not path.is_file() or sha(path.read_bytes())!=row['after']:
                        raise ServiceError(409,'REVISION_CONFLICT','文件另有修改，请保留内容并核对保存记录。')
                    workspace=self.services.workspace_loader()
                    result=self.services.start_sync(actor,{'project_id':project_id,'source_snapshot':row['source_snapshot']},'file-'+operation,'FILE-'+operation[:16],validated_workspace=workspace)
                    if result['state']!='published':raise ServiceError(503,'SOURCE_VALIDATION_FAILED','同步尚未发布，请核对保存记录。')
                    row.update(state='published',updated_at=timestamp())
                    atomic(receipt,json.dumps(row,ensure_ascii=False).encode())
                if row['state'] in {'published','view_pending'}:
                    self.publish(self.services.workspace_loader());row.update(state='completed',updated_at=timestamp(),message='已保存并更新工作台。')
                    atomic(receipt,json.dumps(row,ensure_ascii=False).encode());return row
                raise ServiceError(409,'REVISION_CONFLICT','上次保存未完成，请重新读取文件并核对操作记录。')
            old=path.read_bytes() if path.exists() else None
            if (sha(old) if old is not None else None)!=revision:raise ServiceError(409,'REVISION_CONFLICT','文件已被其他操作更新。保留你的内容，重新读取后合并。')
            if old is None and not re.fullmatch(r'requirements/[A-Za-z0-9_-]+\.md',name):
                raise ServiceError(403,'FORBIDDEN','新增文件仅支持需求文档。')
            row={'id':operation,'fingerprint':fingerprint,'tenant_id':actor.tenant_id,'project_id':project_id,
                'path':name,'actor':actor.principal_id,'created_at':timestamp(),'updated_at':timestamp(),
                'state':'prepared','before':revision,'after':sha(data),'message':'保存处理中。'}
            if old is not None:atomic(folder/'before.bin',old)
            atomic(folder/'after.bin',data);atomic(receipt,json.dumps(row,ensure_ascii=False).encode())
            atomic(path,data)
            sync_started=False
            try:
                workspace=self.services.workspace_loader()
                row.update(state='sync_pending',source_snapshot=workspace['source_sha256'],updated_at=timestamp())
                atomic(receipt,json.dumps(row,ensure_ascii=False).encode());sync_started=True
                result=self.services.start_sync(actor,{'project_id':project_id,'source_snapshot':workspace['source_sha256']},'file-'+operation,'FILE-'+operation[:16],validated_workspace=workspace)
                if result['state']!='published':
                    sync_started=False
                    raise ServiceError(503,'SOURCE_VALIDATION_FAILED','同步未完成，已尝试恢复原文件。')
            except Exception:
                if sync_started:
                    row.update(state='sync_pending',updated_at=timestamp(),message='同步回执尚未确认，文件和保存前版本均保留；请使用原操作重试。')
                    atomic(receipt,json.dumps(row,ensure_ascii=False).encode())
                    raise ServiceError(503,'SERVICE_UNAVAILABLE',row['message']) from None
                if path.is_file() and sha(path.read_bytes())==sha(data):
                    if old is None:path.unlink()
                    else:atomic(path,old)
                    row.update(state='rolled_back',message='未发布，源文件已恢复。')
                else:row.update(state='needs_review',message='文件另有更新，未覆盖；请人工核对。')
                row['updated_at']=timestamp();atomic(receipt,json.dumps(row,ensure_ascii=False).encode())
                raise
            row.update(state='published',updated_at=timestamp(),message='文件与数据库已更新，正在更新网页。')
            atomic(receipt,json.dumps(row,ensure_ascii=False).encode())
            try:self.publish(workspace)
            except Exception:
                row.update(state='view_pending',message='文件与数据库已保存；网页更新失败，可用原操作重试。')
                atomic(receipt,json.dumps(row,ensure_ascii=False).encode())
                raise ServiceError(503,'SERVICE_UNAVAILABLE',row['message']) from None
            row.update(state='completed',updated_at=timestamp(),message='已保存并更新工作台。')
            atomic(receipt,json.dumps(row,ensure_ascii=False).encode());return row
