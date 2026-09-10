"""Owned local maintenance: health recovery, private backups and isolated restore.

Scheduled execution prints only receipts. No credential is passed to a process.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.config import settings,get_database_url
from backend.source_editor import atomic,workspace_lock

def now():return datetime.now(timezone.utc).isoformat()
def checksum(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def run(args,**kwargs):
    result=subprocess.run(args,cwd=ROOT,stderr=subprocess.PIPE,timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,**kwargs)
    if result.returncode:raise RuntimeError('维护命令失败；没有输出连接或私有数据。')
    return result

def backup_root():
    configured=settings().get('DEVPLM_BACKUP_DIR')
    if not configured:raise RuntimeError('请先配置独立的DEVPLM_BACKUP_DIR目录。')
    path=Path(configured).resolve()
    roots=[Path(p).resolve() for p in settings().get('DEVPLM_DATA_ROOTS','').split(os.pathsep) if p]
    if path.drive.lower()!='d:' or path.is_relative_to(ROOT) or any(path.is_relative_to(r) or r.is_relative_to(path) for r in roots):
        raise RuntimeError('备份必须位于独立D盘目录，不能覆盖项目资料。')
    marker=path/'.devplm-backups'
    if path.exists() and any(path.iterdir()) and not marker.is_file():raise RuntimeError('备份目录已有其他内容，拒绝接管。')
    path.mkdir(parents=True,exist_ok=True)
    if not marker.exists():atomic(marker,b'dev-plm private backup directory\n')
    return path

def database_digests(conn):
    from psycopg import sql
    names=[r['table_name'] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='devplm' AND table_type='BASE TABLE' ORDER BY table_name").fetchall()]
    result={}
    for name in names:
        digest=hashlib.sha256();digest.update(b'[');count=0
        with conn.cursor(name='backup_'+uuid4().hex) as cursor:
            cursor.itersize=10
            cursor.execute(sql.SQL('SELECT to_jsonb(t) AS value FROM devplm.{} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(name)))
            for row in cursor:
                if count:digest.update(b',')
                digest.update(json.dumps(row['value'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode());count+=1
        digest.update(b']');result[name]={'rows':count,'sha256':digest.hexdigest()}
    return result

def backup():
    from backend import db
    from tools.workspace_sources import resolve_data_roots
    target=backup_root()/('backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    manifest={'id':target.name,'created_at':now(),'state':'preparing','files':{},'source_roots':[]}
    with workspace_lock(ROOT):
        target.mkdir()
        configured=settings().get('DEVPLM_DATA_ROOTS','')
        roots=resolve_data_roots(ROOT,configured.split(os.pathsep) if configured else None)
        # A shared exported DB snapshot keeps dump and verification digests equal
        # even when discussions are posted while the backup is running.
        with db.connection('admin') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            snapshot=conn.execute('SELECT pg_export_snapshot() AS id').fetchone()['id']
            manifest['database']=database_digests(conn)
            env=settings();user=env.get('DEVPLM_DB_ADMIN_USER','postgres');name=env.get('DEVPLM_DB_NAME','devplm')
            with (target/'database.dump').open('wb') as output:
                run(['docker','compose','exec','-T','postgres','pg_dump','-U',user,'-d',name,'--format=custom','--no-owner','--snapshot='+snapshot],stdout=output)
        with zipfile.ZipFile(target/'sources.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for index,root in enumerate(roots):
                manifest['source_roots'].append({'index':index,'path':str(root)})
                for file in sorted(root.rglob('*')):
                    rel=file.relative_to(root)
                    if any(part.startswith('.') for part in rel.parts):continue
                    if file.is_symlink():raise RuntimeError('来源包含链接，备份停止以免越界。')
                    if file.is_file():archive.write(file,f'root-{index}/'+rel.as_posix())
            for file in sorted((ROOT/'.local/edits').glob('*/*')):
                if file.is_file() and not file.is_symlink():archive.write(file,'edit-history/'+file.relative_to(ROOT/'.local/edits').as_posix())
        for name in ['database.dump','sources.zip']:manifest['files'][name]=checksum(target/name)
        manifest['state']='completed';atomic(target/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode())
    return target

def verify(target):
    import psycopg
    from psycopg.conninfo import make_conninfo
    from psycopg.rows import dict_row
    base=backup_root();target=Path(target).resolve()
    if target.parent!=base or not re.fullmatch(r'backup-\d{8}T\d{6}Z-[0-9a-f]{8}',target.name):raise RuntimeError('仅验证本项目备份。')
    manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    if manifest['state']!='completed' or manifest['id']!=target.name:raise RuntimeError('备份尚未完成。')
    for name in ['database.dump','sources.zip']:
        if checksum(target/name)!=manifest['files'][name]:raise RuntimeError('备份校验和不符。')
    staging=base/('.verify-'+uuid4().hex);staging.mkdir()
    name='devplm_restore_'+uuid4().hex[:20];created=False
    user=settings().get('DEVPLM_DB_ADMIN_USER','postgres')
    try:
        with zipfile.ZipFile(target/'sources.zip') as archive:
            for entry in archive.infolist():
                dest=(staging/entry.filename).resolve()
                if not dest.is_relative_to(staging):raise RuntimeError('备份包含越界文件。')
                if not entry.is_dir():
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(entry) as source,dest.open('wb') as out:shutil.copyfileobj(source,out)
                    with archive.open(entry) as source:
                        if checksum(dest)!=hashlib.sha256(source.read()).hexdigest():raise RuntimeError('源文件恢复不一致。')
        run(['docker','compose','exec','-T','postgres','createdb','-U',user,name],stdout=subprocess.PIPE);created=True
        with (target/'database.dump').open('rb') as source:
            run(['docker','compose','exec','-T','postgres','pg_restore','-U',user,'-d',name,'--no-owner','--exit-on-error'],stdin=source,stdout=subprocess.PIPE)
        with psycopg.connect(make_conninfo(get_database_url('admin'),dbname=name),row_factory=dict_row,options='-c timezone=UTC') as conn:
            restored=database_digests(conn)
        if restored!=manifest['database']:raise RuntimeError('数据库恢复后的逐表内容不一致。')
        # Recovery must be readable by the real API role, not only by postgres.
        from backend.services import Services
        from backend.app import make_app
        from backend.config import account_bindings,secret
        from fastapi.testclient import TestClient
        def restored_connection(role='api'):
            return psycopg.connect(make_conninfo(get_database_url(role),dbname=name),row_factory=dict_row,options='-c search_path=devplm,pg_catalog -c timezone=UTC')
        services=Services(connection=restored_connection)
        account=next(a for a in account_bindings() if a['identifier']=='owner')
        with TestClient(make_app(services)) as client:
            login=client.post('/v1/auth/token',json={'identifier':account['identifier'],'credential':secret(account['credential_ref'])})
            if login.status_code!=200:raise RuntimeError('恢复数据库的实际账号登录未通过。')
            response=client.get('/v1/projects',headers={'Authorization':'Bearer '+login.json()['access_token']})
            if response.status_code!=200 or not response.json()['items']:raise RuntimeError('恢复数据库的API权限或读取未通过。')
        receipt={'ok':True,'verified_at':now(),'table_count':len(restored),'source_archive_restored':True,'database_all_rows_equal':True,'restored_authenticated_api':200}
        atomic(target/'verified.json',json.dumps(receipt).encode());return receipt
    finally:
        if created and re.fullmatch(r'devplm_restore_[0-9a-f]{20}',name):
            run(['docker','compose','exec','-T','postgres','dropdb','-U',user,name],stdout=subprocess.PIPE)
        if staging.resolve().parent==base and staging.name.startswith('.verify-'):shutil.rmtree(staging)

def cycle(force_backup=False):
    from tools.local_stack import ensure
    status_path=ROOT/'.local/maintenance-status.json'
    previous=json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    receipt={**previous,'checked_at':now(),'state':'checking','stage':'ensure'}
    try:
        from tools.runtime_resources import available_memory_mb
        memory=available_memory_mb()
        if memory is None or memory<512:
            receipt.update(state='deferred',message='可用内存不足，自动维护已暂停，未启动额外进程。')
            atomic(status_path,json.dumps(receipt,ensure_ascii=False).encode());return receipt
        ensure()
        receipt.update(state='healthy',message='服务可用，自动维护已运行。')
        today=datetime.now(timezone.utc).date().isoformat()
        if force_backup or not previous.get('backup_at','').startswith(today):
            if memory<2048:
                receipt.update(state='deferred',message='服务可用；可用内存不足2GB，备份顺延，不占用当前工作资源。')
                atomic(status_path,json.dumps(receipt,ensure_ascii=False).encode());return receipt
            if not force_backup and previous.get('backup_attempt_at','').startswith(today):
                receipt.update(state='attention',message='今天的备份未完成，已停止自动重复尝试；请查看维护记录。')
                atomic(status_path,json.dumps(receipt,ensure_ascii=False).encode());return receipt
            receipt['backup_attempt_at']=now()
            atomic(status_path,json.dumps(receipt,ensure_ascii=False).encode())
            receipt['stage']='backup';target=backup()
            receipt['stage']='verify';verified=verify(target)
            receipt.update(backup_at=now(),restore_verified_at=verified['verified_at'],backup_id=target.name,message='服务可用，备份及隔离恢复验证成功。')
        receipt['stage']='complete';receipt.pop('error_type',None);receipt.pop('detail',None)
    except Exception as error:
        from backend.protocol import ServiceError
        if isinstance(error,ServiceError) and error.status==409:
            receipt.update(state='deferred',message='正在保存项目，本次备份顺延到下次维护检查。')
        else:
            receipt.update(state='attention',message='自动维护未完成，请查看维护记录。',error_type=type(error).__name__)
            if isinstance(error,RuntimeError):receipt['detail']=str(error)
    atomic(status_path,json.dumps(receipt,ensure_ascii=False,indent=2).encode())
    return receipt

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['cycle','backup','verify']);parser.add_argument('--backup',dest='backup_id');parser.add_argument('--force-backup',action='store_true');args=parser.parse_args()
    try:
        if args.action=='cycle':result=cycle(args.force_backup)
        elif args.action=='backup':
            target=backup();result={'backup_id':target.name,**verify(target)}
        else:result=verify(backup_root()/args.backup_id)
        print(json.dumps(result,ensure_ascii=True));return 1 if result.get('state')=='attention' else 0
    except Exception as error:print(json.dumps({'ok':False,'error_type':type(error).__name__}));return 1

if __name__=='__main__':raise SystemExit(main())
