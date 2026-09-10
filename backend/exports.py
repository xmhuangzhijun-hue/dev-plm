"""Ordinary-file D snapshots and explicit admin recovery.

Files follow tools.workspace_sources' existing manifest/data.json convention.
No F/G table is written. Snapshot SQL aggregates all seven D tables in one
statement, using one MVCC snapshot without escalating the API role's locks.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import UUID

from .db import D_TABLES, JSON_COLUMNS, DatabaseProblem, identity_rows, require_writer
from .projection import canonical, digest, stable_pk

SCHEMA_VERSION=1
ALLOWED_SCOPES={'discussions','claims','audit','notifications'}

def _json(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
def _hash_bytes(value): return hashlib.sha256(value).hexdigest()
def _member(identity,name):return identity[name] if isinstance(identity,dict) else getattr(identity,name)

def _safe_target(directory,export_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',str(export_id)):
        raise DatabaseProblem('VALIDATION_ERROR','导出编号包含非法路径字符。',422)
    project=Path(directory).resolve(strict=True)
    if not project.is_dir():raise DatabaseProblem('EXPORT_FAILED','导出目标项目目录不存在。',422)
    base=(project/'collaboration-exports').resolve()
    if not base.is_relative_to(project) or base==project:
        raise DatabaseProblem('EXPORT_FAILED','导出目录超出当前项目。',422)
    base.mkdir(exist_ok=True)
    target=(base/str(export_id)).resolve()
    if not target.is_relative_to(base) or target==base:
        raise DatabaseProblem('EXPORT_FAILED','导出编号超出授权目录。',422)
    return project,base,target

def _snapshot_tables(conn,tpk,ppk,export_id):
    from psycopg import sql
    parts=[];parameters=[]
    for table in D_TABLES:
        condition='t.tenant_pk=%s AND t.project_pk=%s'
        values=[tpk,ppk]
        if table=='idempotency_requests':
            condition+=" AND t.lifecycle_state IN ('completed','failed')"
        elif table=='collaboration_exports':
            condition+=" AND t.state IN ('completed','failed') AND t.pk::text<>%s";values.append(str(export_id))
        elif table=='collaboration_audit_events':
            condition+=" AND (t.idempotency_request_pk IS NULL OR EXISTS(SELECT 1 FROM devplm.idempotency_requests i WHERE i.pk=t.idempotency_request_pk AND i.lifecycle_state IN ('completed','failed')))"
        parts.extend([sql.Literal(table),sql.SQL("COALESCE((SELECT jsonb_agg(to_jsonb(t) ORDER BY t.pk) FROM devplm.{} t WHERE "+condition+"),'[]'::jsonb)").format(sql.Identifier(table))])
        parameters.extend(values)
    statement=sql.SQL('''SELECT jsonb_build_object({}) AS tables,
      jsonb_build_object(
       'principals',COALESCE((SELECT jsonb_object_agg(pk::text,jsonb_build_object('id',id,'display_name',display_name))
          FROM devplm.principals WHERE tenant_pk=%s),'{{}}'::jsonb),
       'objects',COALESCE((SELECT jsonb_object_agg(pk::text,jsonb_build_object('id',id,'kind',kind,
          'title',COALESCE(source_data->>'title',source_data->>'name',id)))
          FROM devplm.object_registry WHERE tenant_pk=%s AND project_pk=%s),'{{}}'::jsonb)
      ) AS labels''').format(sql.SQL(',').join(parts))
    parameters.extend([tpk,tpk,ppk])
    return conn.execute(statement,parameters).fetchone()

def _receipt(project,target,manifest,manifest_bytes):
    return {'manifest_path':target.relative_to(project).as_posix()+'/manifest.json',
            'sha256':_hash_bytes(manifest_bytes),'files':len(manifest['files'])+1,
            'high_watermark':manifest['high_watermark'],'counts':manifest['counts']}

def create_snapshot(conn,identity,project_id,export_id,directory,scope):
    """Atomically publish a full recovery snapshot plus requested readable views.

    Services own export-job/idempotency completion. Current unfinished export,
    ledger and related ledger audit are intentionally excluded and declared.
    The directory must come from the shared loader's project_directories map,
    never from the HTTP request body.
    """
    require_writer(identity)
    scopes=list(dict.fromkeys(scope))
    if not scopes or not set(scopes)<=ALLOWED_SCOPES:
        raise DatabaseProblem('VALIDATION_ERROR','导出范围不合法。',422)
    project,base,target=_safe_target(directory,export_id)
    tpk,ppk,apk,actor=identity_rows(conn,identity,project_id)
    if target.exists():
        # No overwrite: a previous completed file publication is an objective result.
        # Verification below mirrors only the generic file checksum envelope; the
        # normal recovery/reader path still uses the shared workspace parser.
        manifest_path=target/'manifest.json'
        if not manifest_path.is_file():raise DatabaseProblem('EXPORT_FAILED','同编号导出目录存在但没有完整清单；未覆盖。',409)
        manifest_bytes=manifest_path.read_bytes()
        manifest=json.loads(manifest_bytes)
        if manifest.get('schema_version')!=SCHEMA_VERSION or manifest.get('authority')!='database-export' or manifest.get('state')!='completed' or manifest.get('project_id')!=project_id or manifest.get('tenant_id')!=_member(identity,'tenant_id') or manifest.get('export_id')!=str(export_id) or manifest.get('requested_scopes')!=scopes:
            raise DatabaseProblem('EXPORT_FAILED','已有导出清单与当前请求范围不一致。',409)
        entries=manifest.get('files')
        if not isinstance(entries,list) or not entries or any(not isinstance(entry,dict) or not {'path','sha256'}<=entry.keys() for entry in entries):
            raise DatabaseProblem('EXPORT_FAILED','已有导出清单缺少完整文件集合。',409)
        seen=set();data_file=None
        for entry in entries:
            file=(target/entry['path']).resolve()
            if not file.is_relative_to(target) or file==manifest_path.resolve() or file in seen or not file.is_file() or _hash_bytes(file.read_bytes())!=entry['sha256']:
                raise DatabaseProblem('EXPORT_FAILED','已有导出校验失败；未覆盖。',409)
            seen.add(file)
            if entry['path']=='data.json':data_file=file
        if data_file is None:
            raise DatabaseProblem('EXPORT_FAILED','已有导出缺少 data.json。',409)
        saved=json.loads(data_file.read_text(encoding='utf-8'))
        if saved.get('tenant_id')!=_member(identity,'tenant_id') or saved.get('project_id')!=project_id or saved.get('export_id')!=str(export_id) or set(saved.get('tables',{}))!=set(D_TABLES):
            raise DatabaseProblem('EXPORT_FAILED','已有协作快照范围或七类D表不完整。',409)
        return _receipt(project,target,manifest,manifest_bytes)
    snapshot=_snapshot_tables(conn,tpk,ppk,export_id)
    tables=snapshot['tables']
    counts={table:len(tables[table]) for table in D_TABLES}
    high_watermark=digest({table:[{'pk':row['pk'],'revision':row.get('revision'),'updated_at':row.get('updated_at')} for row in tables[table]] for table in D_TABLES})
    exclusions={'current_export_id':str(export_id),'unfinished_ledger_states':['reserved','executing'],
                'unfinished_export_states':['queued','running'],'note':'完整7D历史快照包括本次导出之前已完成的导出/账本；本次导出任务的完成回执独立保存，不形成自身哈希循环。'}
    data={'schema_version':SCHEMA_VERSION,'authority':'database-export','tenant_id':_member(identity,'tenant_id'),
          'project_id':project_id,'export_id':str(export_id),'high_watermark':high_watermark,'tables':tables,'labels':snapshot['labels'],'exclusions':exclusions}
    files={'data.json':_json(data)}
    if 'discussions' in scopes:
        lines=['# 讨论导出','',f'项目：{project_id}。本文件为数据库协作快照，不修改需求或项目事实。','']
        for row in tables['discussions']:
            lines += [f'## {row["pk"]}', '', row['title'] if row.get('deleted_at') is None else '（主题已删除）','',
                      f'发言主体：{row["created_by"]}；时间：{row["created_at"]}；版本：{row["revision"]}；对象：{row["target_pk"]}','']
            for post in tables['discussion_posts']:
                if post['discussion_pk']==row['pk']:
                    lines += [f'### 回复 {post["pk"]}', '',post['body'] if post.get('deleted_at') is None else '（回复已删除）','',
                              f'主体：{post["created_by"]}；时间：{post["created_at"]}；版本：{post["revision"]}','']
        files['discussions.md']='\n'.join(lines)+'\n'
    if 'claims' in scopes:files['claims.json']=_json(tables['claims'])
    if 'audit' in scopes:files['audit.json']=_json(tables['collaboration_audit_events'])
    if 'notifications' in scopes:files['notifications.json']=_json(tables['notifications'])
    files['README.md']='# 协作数据快照\n\n这是只读数据库导出；不是项目文件真源。data.json 包含七类D级表及恢复依赖，阅读范围见清单。\n\n讨论首帖正文原样映射到 discussions.title，后续回复在 discussion_posts.body；没有另造摘要。\n\n只有本目录的完整清单和文件哈希校验通过，才能作为恢复依据。未导出内容无法凭项目事实重建。本次尚未完成的导出任务和账本不包含在自己的快照中。\n'
    created=datetime.now(timezone.utc).isoformat()
    manifest={'schema_version':SCHEMA_VERSION,'authority':'database-export','state':'completed','tenant_id':_member(identity,'tenant_id'),
        'project_id':project_id,'export_id':str(export_id),'created_at':created,'high_watermark':high_watermark,
        'requested_scopes':scopes,'actual_tables':list(D_TABLES),'counts':counts,'exclusions':exclusions,
        'files':[{'path':name,'sha256':_hash_bytes(content.encode('utf-8'))} for name,content in sorted(files.items())]}
    manifest_bytes=_json(manifest).encode('utf-8')
    stage=Path(tempfile.mkdtemp(prefix='.tmp-export-',dir=base)).resolve()
    try:
        for name,content in files.items():
            destination=stage/name
            with destination.open('wb') as handle:
                handle.write(content.encode('utf-8'));handle.flush();os.fsync(handle.fileno())
        with (stage/'manifest.json').open('wb') as handle:
            handle.write(manifest_bytes);handle.flush();os.fsync(handle.fileno())
        # Manifest and every data file become visible together under the stable ID.
        os.replace(stage,target)
    finally:
        if stage.exists():
            verified=stage.resolve()
            if verified.is_relative_to(base) and verified!=base:shutil.rmtree(verified)
    return _receipt(project,target,manifest,manifest_bytes)

def restore(conn,snapshot):
    """Restore a shared-parser-verified full D snapshot using a separate admin.

    Existing unequal rows are conflicts, never overwritten. F/G rows must already
    have been rebuilt. All seven D tables and their audit links restore atomically.
    """
    from psycopg import sql
    from psycopg.types.json import Jsonb
    admin=conn.execute('''SELECT r.rolsuper OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname='devplm' AND n.nspowner=r.oid) AS allowed
        FROM pg_roles r WHERE r.rolname=current_user''').fetchone()
    if not admin or not admin['allowed']:
        raise DatabaseProblem('FORBIDDEN','恢复需要独立迁移管理员连接，不能使用API账号。',403)
    if snapshot.get('schema_version')!=SCHEMA_VERSION or snapshot.get('authority')!='database-export':
        raise DatabaseProblem('VALIDATION_ERROR','不支持的协作快照版本或权威类型。',422)
    tables=snapshot.get('tables')
    if not isinstance(tables,dict) or set(tables)!=set(D_TABLES):
        raise DatabaseProblem('VALIDATION_ERROR','恢复包必须完整包含七类D表，不接受F/G表。',422)
    tenant_id=snapshot['tenant_id'];project_id=snapshot['project_id']
    tpk=str(stable_pk(tenant_id,None,'tenants',tenant_id));ppk=str(stable_pk(tenant_id,project_id,'projects',project_id))
    inserted=0
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)',(75041580104519,))
        conn.execute('SET CONSTRAINTS ALL DEFERRED')
        for table in D_TABLES:
            columns=[row['column_name'] for row in conn.execute('''SELECT column_name FROM information_schema.columns
                WHERE table_schema='devplm' AND table_name=%s ORDER BY ordinal_position''',(table,)).fetchall()]
            if not columns:raise DatabaseProblem('VALIDATION_ERROR','数据库缺少恢复目标表；请先迁移。',422)
            seen=set()
            for row in tables[table]:
                if not isinstance(row,dict) or set(row)!=set(columns):
                    raise DatabaseProblem('VALIDATION_ERROR','快照行字段与数据库版本不一致：'+table,422)
                if str(row['tenant_pk'])!=tpk or str(row['project_pk'])!=ppk:
                    raise DatabaseProblem('FORBIDDEN','恢复包含范围外租户或项目。',403)
                pk=str(UUID(str(row['pk'])))
                if pk in seen:raise DatabaseProblem('VALIDATION_ERROR','快照包含重复主键。',422)
                seen.add(pk)
                previous=conn.execute(sql.SQL('SELECT to_jsonb(t) AS data FROM devplm.{} t WHERE pk=%s').format(sql.Identifier(table)),(pk,)).fetchone()
                if previous:
                    if canonical(previous['data'])!=canonical(row):
                        raise DatabaseProblem('REVISION_CONFLICT','现有协作事实与恢复包不同，未覆盖。',409,{'table':table,'id':pk})
                    continue
                statement=sql.SQL('INSERT INTO devplm.{} ({}) VALUES ({})').format(sql.Identifier(table),
                    sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns))
                values=[Jsonb(row[column]) if column in JSON_COLUMNS and row[column] is not None else row[column] for column in columns]
                conn.execute(statement,values);inserted+=1
        conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
    return {'counts':{table:len(tables[table]) for table in D_TABLES},'digest':digest(tables),'inserted':inserted,'unchanged':inserted==0}
