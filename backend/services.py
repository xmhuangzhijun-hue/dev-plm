"""Transactional application services. All project facts remain read-only here."""
from datetime import datetime, timezone
from uuid import UUID, uuid4
import hashlib

from . import db
from .protocol import Identity, ServiceError


def now():
    return datetime.now(timezone.utc)


class Services:
    def __init__(self, connection=None, workspace_loader=None):
        self.connection = connection or db.connection
        if workspace_loader is None:
            from build import load_workspace
            workspace_loader = load_workspace
        self.workspace_loader = workspace_loader
        self.authentication = None
        self._exported = set()
        self._export_directories = None
        self._export_signature = None

    def _refresh_export_coverage(self):
        # With no exported snapshots there is no coverage to parse. Avoid loading
        # every source document and Git history just to read a discussion list.
        roots=getattr(self,'source_roots',None)
        if roots and not any(f.is_file() for root in roots
                for f in root.glob('*/collaboration-exports/*/*')
                if not f.parent.name.startswith('.')):
            self._exported=set()
            self._export_directories=None
            self._export_signature=None
            return
        if self._export_directories is not None:
            signature=sorted((str(f),f.stat().st_mtime_ns,f.stat().st_size) for d in self._export_directories.values()
                for f in (d/'collaboration-exports').glob('*/*') if f.is_file() and not f.parent.name.startswith('.'))
            if signature==self._export_signature:return
        payload=self.workspace_loader()
        self._export_directories=payload['project_directories']
        self._export_signature=sorted((str(f),f.stat().st_mtime_ns,f.stat().st_size) for d in self._export_directories.values()
            for f in (d/'collaboration-exports').glob('*/*') if f.is_file() and not f.parent.name.startswith('.'))
        self._exported={(table,str(row['pk']),row['revision']) for snapshot in payload['collaboration_exports'].values()
            for table,rows in snapshot['tables'].items() for row in rows}

    def issue_token(self, identifier, credential):
        return self.authentication.issue_token(identifier, credential)

    def resolve_identity(self, tenant_id, principal_id):
        with self.connection() as conn:
            pk = db.resolve_pk(conn, 'principals', tenant_id, principal_id)
            row = conn.execute('SELECT roles FROM devplm.principals WHERE pk=%s', (pk,)).fetchone()
            if len(row['roles']) != 1:
                raise ServiceError(401, 'AUTH_REQUIRED', '主体没有有效角色。')
            return Identity(tenant_id, principal_id, row['roles'][0])

    def _tenant(self, identity):
        return db.stable_pk(identity.tenant_id, None, 'tenants', identity.tenant_id)

    def _scope(self, conn, identity, project_id):
        tpk, ppk, apk, actor = db.identity_rows(conn, identity, project_id)
        if actor['roles'] != [identity.role]:
            raise ServiceError(401, 'AUTH_REQUIRED', '主体角色已变化，请重新登录。')
        return tpk, ppk, apk

    def _id(self, conn, table, pk):
        from psycopg import sql
        if pk is None:
            return None
        row = conn.execute(sql.SQL('SELECT id FROM devplm.{} WHERE pk=%s').format(sql.Identifier(table)), (pk,)).fetchone()
        return row['id'] if row else None

    def _row(self, conn, identity, table, row_id, lock=False):
        from psycopg import sql
        try:
            pk = UUID(str(row_id))
        except ValueError:
            raise ServiceError(404, 'NOT_FOUND', '协作对象不存在。') from None
        row = conn.execute(sql.SQL('SELECT * FROM devplm.{} WHERE tenant_pk=%s AND pk=%s' + (' FOR UPDATE' if lock else '')).format(sql.Identifier(table)), (self._tenant(identity), pk)).fetchone()
        if row is None:
            raise ServiceError(404, 'NOT_FOUND', '协作对象不存在。')
        return row

    def _target(self, conn, identity, project_id, target_id):
        pk = db.resolve_pk(conn, 'object_registry', identity.tenant_id, target_id, project_id)
        return conn.execute('SELECT * FROM devplm.object_registry WHERE pk=%s', (pk,)).fetchone()

    def _view(self, conn, table, row):
        out = {'id': str(row['pk']), 'project_id': self._id(conn, 'projects', row['project_pk']), 'revision': row['revision']}
        if table == 'notifications':
            return {**out, 'recipient_id': self._id(conn, 'principals', row['recipient_pk']),
                'payload': row['payload'], 'created_at': row['created_at'], 'read_at': row['read_at']}
        out.update(authority='database', updated_by=self._id(conn, 'principals', row['updated_by']), updated_at=row['updated_at'])
        if table == 'claims':
            return {**out, 'target_id': self._id(conn, 'object_registry', row['target_pk']),
                'claimant_id': self._id(conn, 'principals', row['claimant_pk']), 'state': row['lifecycle_state']}
        # Export coverage is tied to the exact revision, not a mutable flag in D.
        out.update(created_by=self._id(conn, 'principals', row['created_by']), created_at=row['created_at'],
            deleted_at=row['deleted_at'], export_status='exported' if (table,str(row['pk']),row['revision']) in self._exported else 'not_exported')
        if table == 'discussions':
            return {**out, 'target_id': self._id(conn, 'object_registry', row['target_pk']), 'body': row['title']}
        return {**out, 'discussion_id': str(row['discussion_pk']),
            'parent_post_id': str(row['parent_post_pk']) if row['parent_post_pk'] else None, 'body': row['body']}

    def _get(self, identity, table, row_id):
        self._refresh_export_coverage()
        with self.connection() as conn:
            row = self._row(conn, identity, table, row_id)
            if table == 'notifications':
                actor = db.resolve_pk(conn, 'principals', identity.tenant_id, identity.principal_id)
                if row['recipient_pk'] != actor:
                    raise ServiceError(403, 'FORBIDDEN', '只能读取本人通知。')
            return self._view(conn, table, row)

    def _list(self, identity, table, project_id=None, filters=None):
        from psycopg import sql
        self._refresh_export_coverage()
        with self.connection() as conn:
            parts, values = ['tenant_pk=%s', 'deleted_at IS NULL'], [self._tenant(identity)]
            if project_id is not None:
                _, ppk, _ = self._scope(conn, identity, project_id)
                parts.append('project_pk=%s'); values.append(ppk)
            for column, value in (filters or {}).items():
                parts.append(sql.Identifier(column).as_string(conn) + '=%s'); values.append(value)
            rows = conn.execute(sql.SQL('SELECT * FROM devplm.{} WHERE ' + ' AND '.join(parts) + ' ORDER BY created_at,pk').format(sql.Identifier(table)), values).fetchall()
            return [self._view(conn, table, row) for row in rows]

    def list_projects(self, identity):
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM devplm.projects WHERE tenant_pk=%s AND deleted_at IS NULL AND projection_state='published' ORDER BY example,id", (self._tenant(identity),)).fetchall()
            return [{**{k:r[k] for k in ['id','name','type','example','stage']}, 'source_path':r['source_path']} for r in rows]

    def list_requirements(self, identity, project_id):
        with self.connection() as conn:
            tpk, ppk, _ = self._scope(conn, identity, project_id)
            rows = conn.execute("SELECT * FROM devplm.requirements WHERE tenant_pk=%s AND project_pk=%s AND deleted_at IS NULL AND projection_state='published' ORDER BY id", (tpk,ppk)).fetchall()
            return [{k:r[k] for k in ['id','title','original','status','source_path']} for r in rows]

    def list_requirement_changes(self, identity, project_id, requirement_id):
        with self.connection() as conn:
            tpk, ppk, _ = self._scope(conn, identity, project_id)
            rpk = db.resolve_pk(conn, 'requirements', identity.tenant_id, requirement_id, project_id)
            rows = conn.execute('''SELECT c.* FROM devplm.changes c JOIN devplm.change_requirements cr ON cr.change_pk=c.pk
                WHERE cr.requirement_pk=%s AND c.tenant_pk=%s AND c.project_pk=%s AND c.deleted_at IS NULL ORDER BY c.id''', (rpk,tpk,ppk)).fetchall()
            out=[]
            for row in rows:
                data=row['source_data']
                commits=[c['sha'] for c in data.get('git',{}).get('commits',[]) if c.get('sha')]
                out.append({'id':row['id'],'title':row['title'],'requirements':data.get('reqs',[]),
                    'commits':commits,'narrative':row['narrative'],'source_path':row['source_path']})
            return out

    def get_change_diff(self, identity, project_id, change_id):
        with self.connection() as conn:
            self._scope(conn, identity, project_id)
            pk=db.resolve_pk(conn,'changes',identity.tenant_id,change_id,project_id)
            row=conn.execute('SELECT source_data FROM devplm.changes WHERE pk=%s',(pk,)).fetchone()
            facts=row['source_data'].get('git',{})
            files=[]
            for commit in facts.get('commits',[]):
                for f in commit.get('files',[]):
                    hunks=[]
                    for h in f.get('hunks',[]):
                        lines=[line if isinstance(line,str) else {'addition':'+','deletion':'-','context':' ','note':''}.get(line.get('kind'),'')+line.get('text','') for line in h.get('lines',[])]
                        hunks.append({k:h[k] for k in ['old_start','old_count','new_start','new_count']} | {'lines':lines})
                    files.append({'path':f['path'],'added':f.get('additions'),'deleted':f.get('deletions'),'hunks':hunks})
            return {'change_id':change_id,'status':facts.get('status','no_history'),'source':'git',
                'files':files,'notice':facts.get('reason') or facts.get('summary','')}

    def list_principals(self, identity):
        with self.connection() as conn:
            rows=conn.execute("SELECT id,display_name,actor_type,roles FROM devplm.principals WHERE tenant_pk=%s AND deleted_at IS NULL AND projection_state='published' ORDER BY id",(self._tenant(identity),)).fetchall()
            return rows

    def list_tasks(self, identity, principal_id, project_id=None):
        with self.connection() as conn:
            pk=db.resolve_pk(conn,'principals',identity.tenant_id,principal_id)
        return self._list(identity,'claims',project_id,{'claimant_pk':pk,'lifecycle_state':'active'})

    def list_discussions(self, identity, project_id, target_id=None):
        filters={}
        if target_id:
            with self.connection() as conn:
                filters['target_pk']=self._target(conn,identity,project_id,target_id)['pk']
        return self._list(identity,'discussions',project_id,filters)

    def list_posts(self, identity, discussion_id):
        self.get_discussion(identity,discussion_id)
        return self._list(identity,'discussion_posts',filters={'discussion_pk':UUID(discussion_id)})

    def list_claims(self, identity, project_id, state=None):
        return self._list(identity,'claims',project_id,{'lifecycle_state':state} if state else {})

    def list_notifications(self, identity):
        with self.connection() as conn:
            pk=db.resolve_pk(conn,'principals',identity.tenant_id,identity.principal_id)
        return self._list(identity,'notifications',filters={'recipient_pk':pk})

    def get_discussion(self, identity, discussion_id): return self._get(identity,'discussions',discussion_id)
    def get_post(self, identity, post_id): return self._get(identity,'discussion_posts',post_id)
    def get_claim(self, identity, claim_id): return self._get(identity,'claims',claim_id)
    def get_notification(self, identity, notification_id): return self._get(identity,'notifications',notification_id)

    def _conflict(self, conn, table, row):
        audit=conn.execute('SELECT * FROM devplm.collaboration_audit_events WHERE pk=%s',(row['last_audit_pk'],)).fetchone()
        actor=conn.execute('SELECT id,display_name FROM devplm.principals WHERE pk=%s',(row['updated_by'],)).fetchone()
        before=(audit or {}).get('before_value') or {}
        after=(audit or {}).get('after_value') or {}
        fields=[k for k in ['body','title','claimant_pk','lifecycle_state','deleted_at','read_at'] if before.get(k)!=after.get(k)]
        # Return human-visible values; internal DB PKs are resolved for claims.
        def visible(value):
            result={k:value[k] for k in ['body','title','lifecycle_state','deleted_at','read_at'] if k in value}
            if value.get('claimant_pk'):
                result['claimant_id']=self._id(conn,'principals',value['claimant_pk'])
            return result
        details={'current_revision':row['revision'],'changed_by':actor,'changed_at':row['updated_at'],
            'changed_fields':fields,'before':visible(before),'after':visible(after)}
        raise ServiceError(409,'REVISION_CONFLICT',f"{actor['display_name']} 已在 {row['updated_at'].isoformat()} 修改：{', '.join(fields) or '对象状态'}。请读取当前版本后重试。",details)

    def _insert(self, conn, identity, project_id, table, key, request_id, extra):
        from psycopg import sql
        from psycopg.types.json import Jsonb
        tpk,ppk,apk=self._scope(conn,identity,project_id)
        values=dict(pk=uuid4(),tenant_pk=tpk,project_pk=ppk,owner_pk=apk,created_at=now(),updated_at=now(),
            created_by=apk,updated_by=apk,idempotency_key=key,**extra)
        query=sql.SQL('INSERT INTO devplm.{} ({}) VALUES ({}) RETURNING *').format(sql.Identifier(table),
            sql.SQL(',').join(map(sql.Identifier,values)),sql.SQL(',').join(sql.Placeholder() for _ in values))
        row=conn.execute(query,[Jsonb(v) if isinstance(v,dict) else v for v in values.values()]).fetchone()
        audit=db.write_audit(conn,identity,project_id,'create',table,row['pk'],None,row,None,key,request_id)
        row['last_audit_pk']=audit
        return row

    def _write(self, identity, project_id, operation, body, key, request_id, action, status=200):
        with self.connection() as conn:
            self._scope(conn,identity,project_id)
            reservation=db.reserve_idempotency(conn,identity,project_id,operation,key,{'project_id':project_id,'body':body},request_id)
            if reservation['replay']:
                return reservation['body']
            result=action(conn)
            db.complete_idempotency(conn,identity,reservation,status,result)
            return db.json_safe(result)

    def create_discussion(self, identity, project_id, body, key, request_id):
        def action(conn):
            target=self._target(conn,identity,project_id,body['target_id'])
            row=self._insert(conn,identity,project_id,'discussions',key,request_id,
                dict(target_pk=target['pk'],title=body['body'],lifecycle_state='open'))
            return self._view(conn,'discussions',row)
        return self._write(identity,project_id,'discussion.create:'+project_id,body,key,request_id,action,201)

    def create_post(self, identity, discussion_id, body, key, request_id):
        project_id=self.get_discussion(identity,discussion_id)['project_id']
        def action(conn):
            discussion=self._row(conn,identity,'discussions',discussion_id,True)
            if discussion['deleted_at']:
                raise ServiceError(409,'VALIDATION_ERROR','已删除讨论不能追加回复。')
            parent=None
            if body.get('parent_post_id'):
                parent=self._row(conn,identity,'discussion_posts',body['parent_post_id'])
                if parent['discussion_pk']!=discussion['pk'] or parent['deleted_at']:
                    raise ServiceError(422,'VALIDATION_ERROR','父回复必须属于同一讨论且未删除。')
            row=self._insert(conn,identity,project_id,'discussion_posts',key,request_id,
                dict(discussion_pk=discussion['pk'],parent_post_pk=parent['pk'] if parent else None,body=body['body'],lifecycle_state='posted'))
            return self._view(conn,'discussion_posts',row)
        return self._write(identity,project_id,'post.create:'+discussion_id,body,key,request_id,action,201)

    def _notify(self, conn, identity, project_id, claim, key, request_id):
        self._insert(conn,identity,project_id,'notifications',key,request_id,dict(recipient_pk=claim['claimant_pk'],
            cause_audit_pk=claim['last_audit_pk'],lifecycle_state='delivered',delivered_at=now(),
            payload={'kind':'assignment','claim_id':str(claim['pk']),'target_id':self._id(conn,'object_registry',claim['target_pk'])}))

    def _claim_lock(self, conn, target_pk):
        lock=int.from_bytes(hashlib.sha256(str(target_pk).encode()).digest()[:8],'big',signed=True)
        conn.execute('SELECT pg_advisory_xact_lock(%s)',(lock,))

    def create_claim(self, identity, project_id, body, key, request_id):
        def action(conn):
            target=self._target(conn,identity,project_id,body['target_id'])
            if target['kind'] not in ('requirements','changes'):
                raise ServiceError(422,'VALIDATION_ERROR','本轮认领仅支持需求或变更。')
            self._claim_lock(conn,target['pk'])
            existing=conn.execute("SELECT * FROM devplm.claims WHERE target_pk=%s AND lifecycle_state='active' AND deleted_at IS NULL FOR UPDATE",(target['pk'],)).fetchone()
            if existing:
                self._conflict(conn,'claims',existing)
            claimant=db.resolve_pk(conn,'principals',identity.tenant_id,body['claimant_id'])
            row=self._insert(conn,identity,project_id,'claims',key,request_id,
                dict(target_pk=target['pk'],claimant_pk=claimant,lifecycle_state='active'))
            self._notify(conn,identity,project_id,row,key,request_id)
            return self._view(conn,'claims',row)
        return self._write(identity,project_id,'claim.create:'+project_id,body,key,request_id,action,201)

    def _edit(self, identity, table, row_id, body, key, request_id, delete=False):
        from psycopg import sql
        existing=self._get(identity,table,row_id)
        project_id=existing['project_id']
        def action(conn):
            if table=='claims':
                # All claim writers acquire target lock first, then row lock.
                observed=self._row(conn,identity,table,row_id)
                self._claim_lock(conn,observed['target_pk'])
            row=self._row(conn,identity,table,row_id,True)
            _,_,apk=self._scope(conn,identity,project_id)
            if table in ('discussions','discussion_posts') and row['created_by']!=apk:
                raise ServiceError(403,'FORBIDDEN','只能编辑或删除自己的发言。')
            if table=='notifications' and row['recipient_pk']!=apk:
                raise ServiceError(403,'FORBIDDEN','只能修改本人通知。')
            if row['revision']!=body['revision']:
                self._conflict(conn,table,row)
            if row['deleted_at']:
                raise ServiceError(409,'VALIDATION_ERROR','对象已删除。')
            changes=dict(updated_at=now(),updated_by=apk,revision=row['revision']+1)
            if delete:
                changes['deleted_at']=now()
            elif table in ('discussions','discussion_posts'):
                changes['title' if table=='discussions' else 'body']=body['body']
                if table=='discussion_posts': changes['edited_at']=now()
            elif table=='claims':
                changes['lifecycle_state']=body['state']
                changes['released_at']=now() if body['state']=='released' else None
                if body.get('claimant_id'):
                    changes['claimant_pk']=db.resolve_pk(conn,'principals',identity.tenant_id,body['claimant_id'])
                if body['state']=='active':
                    other=conn.execute("SELECT * FROM devplm.claims WHERE target_pk=%s AND pk<>%s AND lifecycle_state='active' AND deleted_at IS NULL",(row['target_pk'],row['pk'])).fetchone()
                    if other:self._conflict(conn,'claims',other)
            else:
                changes.update(read_at=now(),lifecycle_state='read')
            assignments=sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in changes)
            query=sql.SQL('UPDATE devplm.{} SET {} WHERE pk=%s AND tenant_pk=%s AND revision=%s RETURNING *').format(sql.Identifier(table),assignments)
            after=conn.execute(query,[*changes.values(),row['pk'],row['tenant_pk'],body['revision']]).fetchone()
            if after is None:self._conflict(conn,table,self._row(conn,identity,table,row_id))
            after['last_audit_pk']=db.write_audit(conn,identity,project_id,'delete' if delete else 'update',table,row['pk'],row,after,body['revision'],key,request_id)
            if table=='claims' and after['lifecycle_state']=='active' and (row['claimant_pk']!=after['claimant_pk'] or row['lifecycle_state']!='active'):
                self._notify(conn,identity,project_id,after,key,request_id)
            return self._view(conn,table,after)
        return self._write(identity,project_id,f'{table}.{"delete" if delete else "update"}:{row_id}',body,key,request_id,action)

    def update_discussion(self, identity, discussion_id, body, key, request_id):return self._edit(identity,'discussions',discussion_id,body,key,request_id)
    def delete_discussion(self, identity, discussion_id, body, key, request_id):return self._edit(identity,'discussions',discussion_id,body,key,request_id,True)
    def update_post(self, identity, post_id, body, key, request_id):return self._edit(identity,'discussion_posts',post_id,body,key,request_id)
    def delete_post(self, identity, post_id, body, key, request_id):return self._edit(identity,'discussion_posts',post_id,body,key,request_id,True)
    def update_claim(self, identity, claim_id, body, key, request_id):return self._edit(identity,'claims',claim_id,body,key,request_id)
    def update_notification(self, identity, notification_id, body, key, request_id):return self._edit(identity,'notifications',notification_id,body,key,request_id)

    def _job_view(self, row, export=False):
        if export:
            return {'id':str(row['pk']),'state':row['state'],'manifest_path':row['manifest_path'],
                'checksum':row['sha256'],'message':row.get('error_code') or ('导出已发布。' if row['state']=='completed' else row['state'])}
        return {'id':str(row['pk']),'state':row['state'],'source_snapshot':row['source_snapshot'],
            'published_snapshot':row['published_snapshot'],'message':(row.get('error') or {}).get('message','文件投影已发布。')}

    def get_sync(self, identity, job_id):
        with self.connection() as conn:
            return self._job_view(self._row(conn,identity,'sync_jobs',job_id))

    def get_export(self, identity, export_id):
        with self.connection() as conn:
            return self._job_view(self._row(conn,identity,'collaboration_exports',export_id),True)

    def start_sync(self, identity, body, key, request_id, *, validated_workspace=None):
        if identity.role!='owner':
            raise ServiceError(403,'FORBIDDEN','只有租户 owner 可以发布文件投影。')
        project_id=body['project_id']
        from psycopg.types.json import Jsonb
        # Persist work intent before the separately privileged projection writer.
        # A retry resumes this exact job after a crash; it does not create another.
        with self.connection() as conn:
            tpk,ppk,apk=self._scope(conn,identity,project_id)
            reservation=db.reserve_idempotency(conn,identity,project_id,'sync:'+project_id,key,
                {'project_id':project_id,'body':body},request_id,resume=True)
            if reservation['replay']:
                return reservation['body']
            if reservation.get('resume'):
                job=UUID(reservation['body']['id'])
            else:
                job=uuid4()
                conn.execute("""INSERT INTO devplm.sync_jobs(pk,tenant_pk,project_pk,owner_pk,actor_pk,idempotency_key,source_snapshot,state)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,'queued')""",(job,tpk,ppk,apk,apk,key,body['source_snapshot']))
                conn.execute("UPDATE devplm.idempotency_requests SET lifecycle_state='executing',response_body=%s WHERE pk=%s",(Jsonb({'id':str(job)}),reservation['pk']))
        try:
            with self.connection('sync') as sync_conn:
                sync_conn.execute('SELECT pg_advisory_xact_lock(%s)',(int.from_bytes(job.bytes[:8],'big',signed=True),))
                row=self._row(sync_conn,identity,'sync_jobs',str(job),True)
                if row['state'] not in ('published','failed'):
                    payload=validated_workspace if validated_workspace is not None else self.workspace_loader()
                    if body['source_snapshot'].removeprefix('sha256:')!=payload['source_sha256']:
                        raise ValueError('源快照已变化，请读取实际源指纹后重试。')
                    if payload['governance']['project_tenants'].get(project_id)!=identity.tenant_id:
                        raise ValueError('项目文件的租户归属与当前访问范围不一致。')
                    receipt=db.sync(sync_conn,payload,tenant_id=identity.tenant_id,project_id=project_id)
                    # F/G and the publication marker commit together in this role.
                    sync_conn.execute("UPDATE devplm.sync_jobs SET state='published',published_snapshot=%s,updated_at=clock_timestamp() WHERE pk=%s",(receipt['source_sha256'],job))
        except Exception as exc:
            from build import BuildError
            message=str(exc) if isinstance(exc,(BuildError,db.SourcePayloadError,ValueError)) else '同步未发布，请检查文件校验与数据库状态。'
            with self.connection() as conn:
                # If COMMIT's acknowledgement was lost, do not overwrite published.
                conn.execute("UPDATE devplm.sync_jobs SET state='failed',error=%s,updated_at=clock_timestamp() WHERE pk=%s AND state<>'published'",(Jsonb({'code':'SOURCE_VALIDATION_FAILED','message':message}),job))
        with self.connection() as conn:
            current=conn.execute('SELECT * FROM devplm.idempotency_requests WHERE pk=%s FOR UPDATE',(reservation['pk'],)).fetchone()
            if current['lifecycle_state']=='completed':
                return current['response_body']
            result=self._job_view(self._row(conn,identity,'sync_jobs',str(job)))
            db.complete_idempotency(conn,identity,reservation,202,result)
            return db.json_safe(result)

    def create_export(self, identity, project_id, body, key, request_id):
        from .exports import create_snapshot
        from psycopg.types.json import Jsonb
        with self.connection() as conn:
            tpk,ppk,apk=self._scope(conn,identity,project_id)
            reservation=db.reserve_idempotency(conn,identity,project_id,'export:'+project_id,key,
                {'project_id':project_id,'body':body},request_id,resume=True)
            if reservation['replay']:return reservation['body']
            if reservation.get('resume'):
                job=UUID(reservation['body']['id'])
            else:
                job=uuid4()
                conn.execute("""INSERT INTO devplm.collaboration_exports(pk,tenant_pk,project_pk,owner_pk,actor_pk,idempotency_key,state,requested_scopes)
                    VALUES(%s,%s,%s,%s,%s,%s,'queued',%s)""",(job,tpk,ppk,apk,apk,key,sorted(body['scope'])))
                conn.execute("UPDATE devplm.idempotency_requests SET lifecycle_state='executing',response_body=%s WHERE pk=%s",(Jsonb({'id':str(job)}),reservation['pk']))
        # The same persisted id is reused if files published but a DB receipt failed.
        try:
            with self.connection() as conn:
                ledger=conn.execute('SELECT * FROM devplm.idempotency_requests WHERE pk=%s FOR UPDATE',(reservation['pk'],)).fetchone()
                if ledger['lifecycle_state']=='completed':return ledger['response_body']
                payload=self.workspace_loader()
                if payload['governance']['project_tenants'].get(project_id)!=identity.tenant_id:
                    raise ServiceError(403,'FORBIDDEN','项目文件的租户归属与当前访问范围不一致。')
                directory=payload['project_directories'][project_id]
                conn.execute("UPDATE devplm.collaboration_exports SET state='running' WHERE pk=%s",(job,))
                receipt=create_snapshot(conn,identity,project_id,str(job),directory,body['scope'])
                conn.execute("""UPDATE devplm.collaboration_exports SET state='completed',manifest_path=%s,sha256=%s,
                    high_watermark=%s,updated_at=clock_timestamp() WHERE pk=%s""",(receipt['manifest_path'],receipt['sha256'],receipt['high_watermark'],job))
                result=self._job_view(self._row(conn,identity,'collaboration_exports',str(job)),True)
                db.complete_idempotency(conn,identity,reservation,202,result)
            self._export_signature=None
            return db.json_safe(result)
        except ServiceError:
            raise
        except Exception:
            # Intent remains resumable. Any completed package is verified on retry.
            raise ServiceError(503,'EXPORT_FAILED','导出回执未完成；使用同一幂等键重试可核对并接续该导出任务。') from None
