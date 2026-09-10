"""Explicit, private read-only mounts of existing engineering log directories.

No source modification, replication, database projection or directory watcher.
Metadata is cached by file stat; full bodies are read only when opened.
"""
from pathlib import Path
from threading import RLock
from datetime import datetime, timezone
import hashlib
import json
import yaml
from .config import ROOT
from .protocol import ServiceError

CONFIG = ROOT / '.local/log-sources.json'
_cache = {}
_lock = RLock()


def mounts(actor):
    if not CONFIG.exists(): return []
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    return [m for m in data['sources'] if
            {'tenant_id':actor.tenant_id,'principal_id':actor.principal_id} in m.get('readers',[])]


def catalog(actor):
    return [{'id':m['id'],'name':m['name'],'example':False,'log_only':True}
            for m in mounts(actor)]


def resolve(actor, project):
    selected = [m for m in mounts(actor) if m['id']==project]
    if len(selected)!=1: raise ServiceError(404,'NOT_FOUND','日志项目不存在或没有访问权限。')
    root=Path(selected[0]['directory'])
    if not root.is_dir() or root.is_symlink():
        raise ServiceError(503,'SERVICE_UNAVAILABLE','日志来源目录暂不可用。')
    return root.resolve()


def files(root):
    return [p for p in root.glob('*.md') if p.is_file() and not p.is_symlink()
            and p.name!='项目状态.md' and p.resolve().parent==root]


def parse(file):
    if file.stat().st_size>1024*1024:
        raise ValueError('log too large')
    text=file.read_text(encoding='utf-8-sig')
    parts=text.split('---',2)
    if len(parts)!=3 or parts[0].strip(): raise ValueError('missing frontmatter')
    data=yaml.load(parts[1],Loader=getattr(yaml,'CSafeLoader',yaml.SafeLoader))
    if not isinstance(data,dict):raise ValueError('invalid frontmatter')
    return data,parts[2].strip()


def read(actor, project, revision=None):
    root=resolve(actor,project)
    entries=sorted(files(root),key=lambda p:p.name)
    signature=[(p.name,p.stat().st_mtime_ns,p.stat().st_size) for p in entries]
    digest=hashlib.sha256(json.dumps(signature).encode()).hexdigest()
    if revision==digest:return {'revision':digest,'unchanged':True}
    items,errors=[],[]
    with _lock:
        cache=_cache.setdefault(str(root),{})
        names={p.name for p in entries}
        for old in list(cache):
            if old not in names:del cache[old]
        for file,sign in zip(entries,signature):
            try:
                if cache.get(file.name,{}).get('signature')!=sign:
                    data,body=parse(file)
                    heading=next((line.lstrip('# ').strip() for line in body.splitlines() if line.startswith('# ')),file.stem)
                    value=lambda key,default='':str(data.get(key,default) or '')
                    row={'id':value('change_id',file.stem),'title':value('topic',heading),
                         'time':value('last_activity_at') or value('started_at') or value('date'),
                         'stage':value('stage') or value('work_type','未分类'),
                         'env':value('environment') or value('production_status','未注明'),
                         'result':' · '.join(x for x in [value('status'),value('outcome')] if x),
                         'actor':value('responsible_actor') or value('actor') or value('tool'),
                         'before':'','after':'','reqs':[], 'body':'','path':file.name,
                         'record_key':hashlib.sha256(file.name.encode()).hexdigest(),
                         'modified_at':datetime.fromtimestamp(file.stat().st_mtime,timezone.utc).isoformat()}
                    cache[file.name]={'signature':sign,'row':row}
                items.append(cache[file.name]['row'])
            except (ValueError,OSError,yaml.YAMLError):
                errors.append({'path':file.name,'message':'记录格式或读取失败，其他日志仍可查看。'})
    items.sort(key=lambda item:item['modified_at'],reverse=True)
    return {'revision':digest,'items':items,'errors':errors,'checked_at':datetime.now(timezone.utc).isoformat()}


def detail(actor,project,key):
    root=resolve(actor,project)
    for file in files(root):
        if hashlib.sha256(file.name.encode()).hexdigest()==key:
            try:
                _,body=parse(file)
                return {'path':file.name,'body':body}
            except (ValueError,OSError,yaml.YAMLError):
                raise ServiceError(422,'VALIDATION_ERROR','日志内容暂不可读。') from None
    raise ServiceError(404,'NOT_FOUND','记录不存在。')
