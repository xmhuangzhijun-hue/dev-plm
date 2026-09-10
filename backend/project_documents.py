"""Explicitly registered project documents, served live and read-only."""
import hashlib
from pathlib import Path
from .external_logs import mounts
from .protocol import ServiceError

SECTIONS={'overview':'项目总览','requirements':'需求与迭代','ui':'UI与页面',
          'fields':'字段与数据','api':'API接口','development':'开发实现',
          'tests':'测试与验收','operations':'运维与发布','audit':'审计与安全'}


def mount(actor,project):
    selected=[m for m in mounts(actor) if m['id']==project]
    if len(selected)!=1:raise ServiceError(404,'NOT_FOUND','项目不存在或没有权限。')
    return selected[0]


def document_key(item):
    return hashlib.sha256(item['path'].encode()).hexdigest()


def available(item):
    path=Path(item['path'])
    return path.is_file() and not any(p.is_symlink() for p in [path,*path.parents])


def section(actor,project,kind):
    m=mount(actor,project)
    if kind not in SECTIONS:raise ServiceError(404,'NOT_FOUND','栏目不存在。')
    data=m.get('sections',{}).get(kind,{})
    items=[{'key':document_key(d),'title':d['title'],'available':available(d),
            'source':Path(d['path']).name} for d in data.get('documents',[])]
    return {'title':SECTIONS[kind],'note':data.get('note','尚未登记独立资料，可查看项目日志中的工作记录。'),
            'items':items,'sections':[{'id':k,'title':v,'count':sum(available(d) for d in m.get('sections',{}).get(k,{}).get('documents',[]))} for k,v in SECTIONS.items()]}


def document(actor,project,key,revision=None):
    m=mount(actor,project)
    for section in m.get('sections',{}).values():
        for item in section.get('documents',[]):
            if document_key(item)!=key:continue
            if not available(item):raise ServiceError(404,'NOT_FOUND','来源文件不存在或为链接。')
            path=Path(item['path'])
            if path.suffix.lower() not in {'.md','.json','.yaml','.yml','.sql','.txt'} or path.stat().st_size>1024*1024:
                raise ServiceError(422,'VALIDATION_ERROR','来源格式或大小暂不支持在线阅读。')
            try:raw=path.read_bytes();body=raw.decode('utf-8-sig')
            except (OSError,UnicodeError):raise ServiceError(503,'SERVICE_UNAVAILABLE','来源暂不可读。') from None
            digest=hashlib.sha256(raw).hexdigest()
            if digest==revision:return {'revision':digest,'unchanged':True}
            return {'title':item['title'],'source':path.name,'body':body,'revision':digest}
    raise ServiceError(404,'NOT_FOUND','资料未登记或没有权限。')
