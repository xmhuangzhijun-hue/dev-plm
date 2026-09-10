"""Explicit isolated Compose down -v / fresh-cluster F/G recovery acceptance.

Original application database is never stopped. Because bind mounts survive
down -v, the dedicated drill data is renamed and retained, then rebuilt empty.
"""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def run():
    from backend.config import settings
    from backend import db
    from backend.manage import provision_logins
    from backend.rehearse import temporary_settings
    from backend.capture_database import capture,assert_projection_equal
    from build import load_workspace
    original=settings();base=Path(original['DEVPLM_PG_DATA']).resolve()
    if base.drive.lower()!='d:' or not (base/'.devplm-owned').is_file():raise ValueError('Expected owned D-drive application storage')
    run_id=uuid4().hex;parent=base.parent/'drills'/run_id
    parent.mkdir(parents=True,exist_ok=False)
    (parent/'.owned').write_text(run_id,encoding='utf-8')
    data=parent/'data';data.mkdir()
    import socket
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={'DEVPLM_PG_DATA':data.as_posix(),'DEVPLM_DB_PORT':str(port),'DEVPLM_DB_NAME':'devplm_rebuild_'+run_id}
    project='devplm-rebuild-'+run_id
    def compose(*args):
        child={**os.environ,**env}
        result=subprocess.run(['docker','compose','-p',project,'--env-file',str(ROOT/'.env'),*args],cwd=ROOT,env=child,capture_output=True)
        if result.returncode:raise RuntimeError('Isolated Compose operation failed: '+args[0])
    def wait_for_database():
        # Compose's container-local healthcheck does not establish that the
        # Windows published TCP endpoint accepts the configured authenticated
        # connection. Retry this read-only check, never a migration or sync.
        deadline=time.monotonic()+45
        while True:
            try:
                with db.connection('admin') as conn:conn.execute('SELECT 1')
                return
            except db.DatabaseProblem as exc:
                if exc.code!='DATABASE_UNAVAILABLE' or time.monotonic()>=deadline:raise
                time.sleep(1)
    phase='start';summary={'ok':False,'run_id':run_id,'application_database_untouched':True}
    try:
        sources=load_workspace(ROOT)
        with temporary_settings(env):
            compose('up','-d','--wait','postgres')
            wait_for_database()
            with db.connection('admin') as conn:db.migrate(conn);provision_logins(conn)
            with db.connection('sync') as conn:db.sync(conn,sources)
            with db.connection('admin') as conn:before=capture(conn,sources['source_sha256']);system_before=conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()['system_identifier']
            phase='down_and_rotate'
            compose('down','-v')
            retained=parent/'retained-before'
            if (parent/'.owned').read_text()!=run_id or not data.resolve().is_relative_to(parent.resolve()) or not retained.resolve().is_relative_to(parent.resolve()) or data.is_symlink() or retained.exists():raise ValueError('Drill path ownership check failed')
            data.rename(retained);data.mkdir()
            phase='fresh_cluster'
            compose('up','-d','--wait','postgres')
            wait_for_database()
            phase='fresh_admin_migration'
            with db.connection('admin') as conn:
                fresh=conn.execute("SELECT to_regnamespace('devplm') AS schema").fetchone()['schema'] is None
                system_after=conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()['system_identifier']
                db.migrate(conn);provision_logins(conn)
            if not fresh or system_before==system_after:raise AssertionError('Cluster was not recreated empty')
            phase='fresh_sync'
            with db.connection('sync') as conn:db.sync(conn,sources)
            phase='fresh_capture'
            with db.connection('admin') as conn:after=capture(conn,sources['source_sha256'])
            assert_projection_equal(before,after)
            summary.update(ok=True,compose_down_v_executed=True,bind_mount_rotated_not_deleted=True,fresh_cluster=True,system_identifier_changed=True,
                source_sha256=sources['source_sha256'],fg_all_columns_restored=True,
                tables={name:{'before':row['sha256'],'after':after['tables'][name]['sha256'],'count':row['count']} for name,row in before['tables'].items() if name in db.F_TABLES})
    except Exception as exc:summary.update(phase=phase,error_type=type(exc).__name__,error_code=getattr(exc,'code','DRILL_FAILED'))
    finally:
        try:compose('down','-v');summary['drill_containers_stopped']=True
        except Exception:summary['drill_containers_stopped']=False
        (ROOT/'docs/round6-compose-rebuild.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-explicit',action='store_true');args=parser.parse_args()
    if not args.run_explicit:parser.error('--run-explicit is required')
    result=run();print(json.dumps({k:v for k,v in result.items() if k!='tables'}));raise SystemExit(0 if result['ok'] else 1)
