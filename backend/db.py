"""PostgreSQL access, reversible migration, single-direction projection and D helpers.

DSNs come only from backend.config.get_database_url(role); never logged. The API
login must not own the schema, be superuser, or inherit devplm_sync. The migration
admin login is separate from both runtime logins.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from .projection import F_TABLES, SourcePayloadError, canonical, digest, prepare_rows, stable_pk

D_TABLES=('discussions','discussion_posts','claims','notifications','idempotency_requests','collaboration_audit_events','collaboration_exports')
E_TABLES=('sync_jobs','presence')
MIGRATIONS=Path(__file__).resolve().parent/'migrations'
JSON_COLUMNS={'source_data','onboarding','steps','hunks','findings','document','payload','before_value','after_value','response_body','error'}

class DatabaseProblem(RuntimeError):
    def __init__(self,code,message,status=409,details=None):
        super().__init__(message)
        self.code,self.message,self.status,self.details=code,message,status,details or {}

def _value(identity,name):
    return identity[name] if isinstance(identity,dict) else getattr(identity,name)

def connection(role='api'):
    if role not in ('api','sync','admin'): raise ValueError('Unsupported database role')
    try:
        import psycopg
        from psycopg.rows import dict_row
        from .config import get_database_url
        conn=psycopg.connect(get_database_url(role),row_factory=dict_row,autocommit=False,
                             options='-c search_path=devplm,pg_catalog -c timezone=UTC')
    except ImportError:
        raise DatabaseProblem('DATABASE_NOT_CONFIGURED','需要已批准的 psycopg 3 与 backend.config.get_database_url。',503) from None
    except Exception:
        raise DatabaseProblem('DATABASE_UNAVAILABLE','数据库连接失败；请检查已登记配置和服务状态。',503) from None
    if role!='admin':
        try:
            info=conn.execute("""SELECT r.rolsuper, r.rolcreaterole,
                pg_has_role(current_user,'devplm_api','MEMBER') AS api,
                pg_has_role(current_user,'devplm_sync','MEMBER') AS sync,
                EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname='devplm' AND n.nspowner=r.oid) AS owns_schema
                FROM pg_roles r WHERE r.rolname=current_user""").fetchone()
            unsafe=not info or info['rolsuper'] or info['rolcreaterole'] or info['owns_schema']
            unsafe=unsafe or not info[role] or (role=='api' and info['sync']) or (role=='sync' and info['api'])
            if unsafe: raise DatabaseProblem('DATABASE_ROLE_UNSAFE','运行账号权限不隔离；API、同步与迁移账号必须分开。',503)
            conn.rollback()
        except Exception as exc:
            conn.close()
            if isinstance(exc,DatabaseProblem):raise
            raise DatabaseProblem('DATABASE_ROLE_UNSAFE','数据库权限角色未准备；先执行已授权迁移与账号配置。',503) from None
    return conn

def migrate(conn,direction='up'):
    """Apply/revert migration 001 inside a transaction; repeat up/down is safe."""
    if direction not in ('up','down'):raise ValueError('direction must be up or down')
    sql_path=MIGRATIONS/f'001_initial.{direction}.sql'
    script=sql_path.read_text(encoding='utf-8')
    checksum=hashlib.sha256((MIGRATIONS/'001_initial.up.sql').read_bytes()).hexdigest()
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)',(75041580104517,))
        present=conn.execute("SELECT to_regclass('devplm.schema_migrations') AS relation").fetchone()['relation']
        if direction=='up' and present:
            existing=conn.execute("SELECT sha256 FROM devplm.schema_migrations WHERE version='001'").fetchone()
            if existing:
                if existing['sha256'].strip()!=checksum:
                    raise DatabaseProblem('MIGRATION_CHANGED','已执行的迁移文件发生变化；请新增迁移，不覆盖历史。',409)
                return {'version':'001','direction':'up','changed':False,'sha256':checksum}
        if direction=='down' and not present:
            return {'version':'001','direction':'down','changed':False}
        conn.execute(script)
        if direction=='up':
            conn.execute('INSERT INTO devplm.schema_migrations(version,sha256) VALUES(%s,%s)',('001',checksum))
    return {'version':'001','direction':direction,'changed':True,'sha256':checksum if direction=='up' else None}

def fact_digest(conn):
    """Hash every F/G column, including explicit tombstones; no runtime clocks."""
    from psycopg import sql
    tables={}
    counts={}
    for table in F_TABLES:
        result=conn.execute(sql.SQL('SELECT * FROM devplm.{} ORDER BY pk').format(sql.Identifier(table))).fetchall()
        tables[table]=digest(result)
        counts[table]=len(result)
    return {'fact_sha256':digest(tables),'tables':tables,'counts':counts}

def sync(conn,payload,tenant_id=None,project_id=None):
    """Only F/G mutations; no filesystem writes, D export ingestion or D mutation.

    The shared loader must finish validation first. A transaction/advisory lock
    publishes all rows atomically. Missing sources are removed; outstanding D FK
    references require explicit file tombstones, otherwise the whole sync rolls back.
    """
    from psycopg import sql
    from psycopg.errors import ForeignKeyViolation
    from psycopg.types.json import Jsonb
    projected=prepare_rows(payload)
    if project_id is not None and tenant_id is None:
        raise DatabaseProblem('FORBIDDEN','按项目同步必须明确租户范围。',403)
    scope_tenant=stable_pk(tenant_id,None,'tenants',tenant_id) if tenant_id is not None else None
    scope_project=stable_pk(tenant_id,project_id,'projects',project_id) if project_id is not None else None
    if tenant_id is not None:
        if not any(r['pk']==scope_tenant for r in projected['tenants']):
            raise DatabaseProblem('NOT_FOUND','同步租户不存在。',404)
        if project_id is not None and not any(r['pk']==scope_project and r['tenant_pk']==scope_tenant for r in projected['projects']):
            raise DatabaseProblem('NOT_FOUND','同步项目不属于该租户。',404)
        projected={table:[row for row in rows if row['tenant_pk']==scope_tenant and
                   (scope_project is None or row['project_pk'] is None or row['project_pk']==scope_project)]
                   for table,rows in projected.items()}
    try:
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(%s)',(75041580104518,))
            conn.execute('SET CONSTRAINTS ALL DEFERRED')
            before=fact_digest(conn)
            for table,rows in projected.items():
                if not rows:continue
                columns=list(rows[0])
                if any(set(row)!=set(columns) for row in rows):raise SourcePayloadError('Projection row columns differ in '+table)
                identifiers=sql.SQL(',').join(map(sql.Identifier,columns))
                placeholders=sql.SQL(',').join(sql.Placeholder() for _ in columns)
                assignments=sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(c),sql.Identifier(c)) for c in columns if c!='pk')
                statement=sql.SQL('INSERT INTO devplm.{} AS existing ({}) VALUES ({}) ON CONFLICT(pk) DO UPDATE SET {} WHERE to_jsonb(existing) IS DISTINCT FROM to_jsonb(EXCLUDED)').format(
                    sql.Identifier(table),identifiers,placeholders,assignments)
                values=[tuple(Jsonb(row[c]) if c in JSON_COLUMNS and row[c] is not None else row[c] for c in columns) for row in rows]
                with conn.cursor() as cursor:cursor.executemany(statement,values)
            for table in reversed(F_TABLES):
                keep=[row['pk'] for row in projected[table]]
                where='NOT(pk=ANY(%s::uuid[]))';parameters=[keep]
                if scope_tenant is not None:where+=' AND tenant_pk=%s';parameters.append(scope_tenant)
                if scope_project is not None:where+=' AND (project_pk IS NULL OR project_pk=%s)';parameters.append(scope_project)
                conn.execute(sql.SQL('DELETE FROM devplm.{} WHERE '+where).format(sql.Identifier(table)),parameters)
            # Catch missing D targets here, before committing a partial snapshot.
            conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            after=fact_digest(conn)
    except ForeignKeyViolation as exc:
        raise DatabaseProblem('SOURCE_DELETION_REQUIRES_TOMBSTONE',
            '源对象已删除或引用不完整，但仍有外键引用；提供完整文件墓碑后重试。整个同步已回滚。',409,
            {'constraint':exc.diag.constraint_name}) from None
    return {'source_sha256':payload['source_sha256'],**after,'unchanged':before['fact_sha256']==after['fact_sha256']}

def resolve_pk(conn,table,tenant_id,object_id,project_id=None):
    """Resolve explicit file IDs to stable PKs; never derive an actor from a label."""
    from psycopg import sql
    if table not in F_TABLES:raise ValueError('Only F/G lookup tables are accepted')
    tenant_pk=stable_pk(tenant_id,None,'tenants',tenant_id)
    predicates=['tenant_pk=%s','id=%s','deleted_at IS NULL',"projection_state='published'"]
    values=[tenant_pk,str(object_id)]
    if project_id is not None:
        predicates.append('project_pk=%s');values.append(stable_pk(tenant_id,project_id,'projects',project_id))
    result=conn.execute(sql.SQL('SELECT * FROM devplm.{} WHERE '+ ' AND '.join(predicates)).format(sql.Identifier(table)),values).fetchall()
    if len(result)!=1:
        raise DatabaseProblem('NOT_FOUND','对象不存在、不可用或标识不唯一。',404)
    return result[0]['pk']

def identity_rows(conn,identity,project_id):
    tenant_id=_value(identity,'tenant_id');principal_id=_value(identity,'principal_id')
    tpk=stable_pk(tenant_id,None,'tenants',tenant_id)
    ppk=resolve_pk(conn,'projects',tenant_id,project_id)
    apk=resolve_pk(conn,'principals',tenant_id,principal_id)
    actor=conn.execute('SELECT * FROM devplm.principals WHERE tenant_pk=%s AND pk=%s',(tpk,apk)).fetchone()
    return tpk,ppk,apk,actor

def require_writer(identity):
    if _value(identity,'role') not in ('owner','maintainer'):
        raise DatabaseProblem('FORBIDDEN','viewer 不能写协作数据。',403)

def reserve_idempotency(conn,identity,project_id,operation,idempotency_key,body,request_id,resource_id=None,resume=False):
    """Reserve within the caller's transaction; advisory lock serializes retries.

    Normal callers complete before commit. Durable jobs may opt into resume=True
    and commit their job/reservation before separately executing the operation.
    Do not use this for credential/token calls.
    Returned replay=True means return the stored status/body without another write.
    """
    require_writer(identity)
    if not idempotency_key or len(idempotency_key)>200:
        raise DatabaseProblem('VALIDATION_ERROR','需要有效 Idempotency-Key（1–200 字符）。',422)
    tpk,ppk,apk,actor=identity_rows(conn,identity,project_id)
    fingerprint=digest({'project_id':project_id,'operation':operation,'resource_id':resource_id,'body':body})
    lock=int.from_bytes(hashlib.sha256(canonical([str(tpk),str(apk),operation,idempotency_key]).encode()).digest()[:8],'big',signed=True)
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(lock,))
    existing=conn.execute('''SELECT * FROM devplm.idempotency_requests
        WHERE tenant_pk=%s AND actor_pk=%s AND operation=%s AND idempotency_key=%s FOR UPDATE''',
        (tpk,apk,operation,idempotency_key)).fetchone()
    if existing:
        if existing['request_sha256'].strip()!=fingerprint:
            raise DatabaseProblem('IDEMPOTENCY_CONFLICT','相同幂等键已用于不同请求内容。',409)
        if existing['lifecycle_state']=='completed':
            return {'pk':existing['pk'],'replay':True,'status':existing['response_status'],'body':existing['response_body']}
        if resume:
            return {'pk':existing['pk'],'replay':False,'resume':True,'body':existing['response_body'],
                    'project_id':project_id,'operation':operation,'idempotency_key':idempotency_key,'request_id':request_id}
        raise DatabaseProblem('REQUEST_IN_PROGRESS','该请求已有未完成账本，需要核对结果后重试。',409)
    now=datetime.now(timezone.utc)
    ledger_pk=uuid4()
    conn.execute('''INSERT INTO devplm.idempotency_requests
        (pk,tenant_pk,project_pk,owner_pk,created_at,updated_at,created_by,updated_by,idempotency_key,lifecycle_state,
         actor_pk,operation,request_sha256,expires_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'reserved',%s,%s,%s,%s)''',
        (ledger_pk,tpk,ppk,apk,now,now,apk,apk,idempotency_key,apk,operation,fingerprint,now+timedelta(days=1)))
    return {'pk':ledger_pk,'replay':False,'project_id':project_id,'operation':operation,
            'idempotency_key':idempotency_key,'request_id':request_id}

def write_audit(conn,identity,project_id,action,table,target_pk,before,after,expected_revision,
                idempotency_key,request_id,result='succeeded',reason_code=None):
    """Append audit and attach its FK in the same caller-owned DB transaction."""
    from psycopg import sql
    from psycopg.types.json import Jsonb
    targets={'discussions':'discussion_pk','discussion_posts':'post_pk','claims':'claim_pk','notifications':'notification_pk','idempotency_requests':'idempotency_request_pk'}
    if table not in targets:raise ValueError('Unsupported auditable collaboration table')
    tpk,ppk,apk,actor=identity_rows(conn,identity,project_id)
    audit_pk=uuid4();now=datetime.now(timezone.utc)
    result_revision=after.get('revision') if isinstance(after,dict) else None
    statement=sql.SQL('''INSERT INTO devplm.collaboration_audit_events
        (pk,tenant_pk,project_pk,owner_pk,actor_pk,actor_type,action,target_kind,{},before_value,after_value,
         expected_revision,resulting_revision,idempotency_key,request_id,result,reason_code,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''').format(sql.Identifier(targets[table]))
    conn.execute(statement,(audit_pk,tpk,ppk,apk,apk,actor['actor_type'],action,table,target_pk,
        Jsonb(json_safe(before)) if before is not None else None,Jsonb(json_safe(after)) if after is not None else None,
        expected_revision,result_revision,idempotency_key,request_id,result,reason_code,now,now))
    conn.execute(sql.SQL('UPDATE devplm.{} SET last_audit_pk=%s WHERE tenant_pk=%s AND project_pk=%s AND pk=%s').format(sql.Identifier(table)),
        (audit_pk,tpk,ppk,target_pk))
    return audit_pk

def complete_idempotency(conn,identity,reservation,status,body):
    from psycopg.types.json import Jsonb
    if reservation.get('replay'):return reservation
    before=conn.execute('SELECT * FROM devplm.idempotency_requests WHERE pk=%s FOR UPDATE',(reservation['pk'],)).fetchone()
    if not before:raise DatabaseProblem('NOT_FOUND','幂等账本不存在。',404)
    tpk,ppk,apk,_=identity_rows(conn,identity,reservation['project_id'])
    if (before['tenant_pk'],before['project_pk'],before['actor_pk'])!=(tpk,ppk,apk):
        raise DatabaseProblem('FORBIDDEN','幂等账本不属于当前请求主体。',403)
    now=datetime.now(timezone.utc)
    after=conn.execute('''UPDATE devplm.idempotency_requests SET lifecycle_state='completed',response_status=%s,
        response_body=%s,revision=revision+1,updated_at=%s WHERE pk=%s RETURNING *''',
        (status,Jsonb(json_safe(body)),now,reservation['pk'])).fetchone()
    write_audit(conn,identity,reservation['project_id'],reservation['operation']+'.completed','idempotency_requests',
        reservation['pk'],before,after,before['revision'],reservation['idempotency_key'],reservation['request_id'])
    return {'pk':reservation['pk'],'replay':False,'status':status,'body':body}

def json_safe(value):
    import json
    return json.loads(canonical(value))
