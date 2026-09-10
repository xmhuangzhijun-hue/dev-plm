"""Explicit local migration, sync and serving commands. No automatic installation."""
import argparse
import json
import os
from pathlib import Path

from . import db
from .config import ROOT, ConfigurationError, secret, settings


def provision_logins(conn):
    """Provision distinct non-owning login roles using registered secrets only."""
    from psycopg import sql
    env=settings()
    for role in ('api','sync'):
        name=env.get('DEVPLM_DB_'+role.upper()+'_USER') or 'devplm_'+role+'_login'
        value=secret(env.get('DEVPLM_DB_'+role.upper()+'_SECRET'))
        present=conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(name,)).fetchone()
        if not present:
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT PASSWORD {}').format(sql.Identifier(name),sql.Literal(value)))
        else:
            current=conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=%s',(name,)).fetchone()
            if any(current.values()):
                raise ConfigurationError('现有运行登录权限过大，停止配置。')
        conn.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier('devplm_'+role),sql.Identifier(name)))
    return {'runtime_roles':'separate_non_superuser_logins','configured':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['migrate','rollback','sync','serve','source-hash','restore-export'])
    parser.add_argument('--data-root',action='append',type=Path)
    parser.add_argument('--project')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    env=settings()
    roots=args.data_root or ([Path(p) for p in env['DEVPLM_DATA_ROOTS'].split(os.pathsep) if p] if env.get('DEVPLM_DATA_ROOTS') else None)
    if roots:os.environ['DEVPLM_DATA_ROOTS']=os.pathsep.join(str(p.resolve()) for p in roots)
    try:
        if args.action=='serve':
            import uvicorn
            uvicorn.run('backend.app:app',host='127.0.0.1',port=args.port,access_log=False,log_level='warning')
            return 0
        if args.action in ('migrate','rollback'):
            with db.connection('admin') as conn:
                receipt=db.migrate(conn,'up' if args.action=='migrate' else 'down')
                if args.action=='migrate':receipt['roles']=provision_logins(conn)
        else:
            from build import load_workspace
            workspace=load_workspace(ROOT,data_roots=roots)
            if args.action=='source-hash':receipt={'source_sha256':workspace['source_sha256']}
            elif args.action=='restore-export':
                from .exports import restore
                if args.project not in workspace['collaboration_exports']:
                    raise ValueError('项目没有已校验的完整协作导出。')
                with db.connection('admin') as conn:
                    receipt=restore(conn,workspace['collaboration_exports'][args.project])
            else:
                scope={}
                if args.project:
                    tenant=(workspace.get('governance') or {}).get('project_tenants',{}).get(args.project)
                    if not tenant:raise ValueError('指定项目没有有效的租户来源映射。')
                    scope={'tenant_id':tenant,'project_id':args.project}
                with db.connection('sync') as conn:receipt=db.sync(conn,workspace,**scope)
        print(json.dumps(db.json_safe(receipt),ensure_ascii=False))
        return 0
    except Exception as exc:
        from build import BuildError
        safe=isinstance(exc,(ConfigurationError,db.DatabaseProblem,db.SourcePayloadError,BuildError,ValueError))
        print(json.dumps({'ok':False,'error':getattr(exc,'code','LOCAL_OPERATION_FAILED'),
            'message':str(exc) if safe else '本机操作未完成；敏感连接细节不输出。'},ensure_ascii=False))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
