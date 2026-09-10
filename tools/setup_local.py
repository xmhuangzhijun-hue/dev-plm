"""Explicit Windows setup for fresh local dev-plm credentials and nonsecret config.

No existing .env, data directory or credential is overwritten. Secret values are
generated directly into the central private store, never returned or logged.
"""
import argparse
from datetime import datetime,timezone
import json,os,re,secrets,subprocess,sys
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]

def initialize(data_directory):
    if os.name!='nt':raise ValueError('This setup targets Windows')
    data=Path(data_directory).resolve()
    if data.drive.lower()!='d:' or data==Path(data.anchor) or data.is_relative_to(ROOT) or data.exists():
        raise ValueError('Choose a NEW dedicated D-drive directory outside the repository')
    if (ROOT/'.env').exists() or (ROOT/'.local/accounts.json').exists():raise ValueError('Local configuration already exists; no overwrite')
    store=Path(os.environ['LOCALAPPDATA'])/'XiaomoSecrets'
    registry=store/'registry.yaml'
    original=registry.read_bytes();document=yaml.safe_load(original)
    entries=document['entries']
    if not isinstance(entries,list):raise ValueError('Unsupported registry format')
    target=store/'private/databases/devplm-local'
    if target.exists():raise ValueError('Dedicated credential directory already exists; inspect prior setup')
    lock=store/'devplm-registration.lock'
    with lock.open('x'):
        pass
    try:
        sid=subprocess.check_output(['powershell','-NoProfile','-Command','[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],text=True).strip()
        if not re.fullmatch(r'S-1-[0-9-]+',sid):raise ValueError('Unable to resolve current Windows SID')
        target.mkdir(parents=True)
        acl=subprocess.run(['icacls',str(target),'/inheritance:r','/grant:r',f'*{sid}:(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],capture_output=True)
        if acl.returncode:raise ValueError('Private directory ACL setup failed; no credentials written')
        year=datetime.now().year;prefix=f'SEC-{year}-'
        sequence=max([int(e['id'].split('-')[-1]) for e in entries if str(e.get('id','')).startswith(prefix)]+[0])
        refs={};now=datetime.now(timezone.utc).isoformat()
        for name in ['admin','api','sync','jwt','owner','maintainer','viewer','other-owner','outsider']:
            sequence+=1;reference=prefix+str(sequence).zfill(3)
            path=target/(name+'.txt')
            with path.open('x',encoding='utf-8') as handle:handle.write(secrets.token_urlsafe(48))
            refs[name]=reference
            entries.append({'id':reference,'type':'password' if name!='jwt' else 'token','service':'dev-plm local','account':name,
                'purpose':'Local development runtime and explicitly authorized integration acceptance',
                'secret_location':'file:'+path.relative_to(store).as_posix(),'source':'Local cryptographic random generation',
                'created_at':now,'last_verified_at':None,'rotate_after':None,'status':'active','notes':'Private ACL file; never copy value to repository or logs'})
        document['updated_at']=now
        if registry.read_bytes()!=original:raise ValueError('Registry changed concurrently; keep new files private and reconcile before retry')
        temporary=store/'registry.devplm.pending.yaml'
        with temporary.open('x',encoding='utf-8') as handle:yaml.safe_dump(document,handle,allow_unicode=True,sort_keys=False)
        os.replace(temporary,registry)
        with (store/'audit-log.md').open('a',encoding='utf-8') as handle:handle.write('\n'+now+' dev-plm: added nine local runtime credentials; values retained only in private ACL files.\n')
        data.mkdir(parents=True)
        (data/'.devplm-owned').write_text('devplm-local dedicated storage\n',encoding='utf-8')
        local=ROOT/'.local';local.mkdir(exist_ok=True)
        bindings=[{'identifier':name,'tenant_id':'isolated-demo' if name=='outsider' else 'devplm-local','principal_id':name,'credential_ref':refs[name]} for name in ['owner','maintainer','viewer','other-owner','outsider']]
        (local/'accounts.json').write_text(json.dumps(bindings,indent=2)+'\n',encoding='utf-8')
        values={'DEVPLM_DB_ADMIN_SECRET':refs['admin'],'DEVPLM_DB_API_SECRET':refs['api'],'DEVPLM_DB_SYNC_SECRET':refs['sync'],
            'DEVPLM_JWT_SECRET':refs['jwt'],'DEVPLM_POSTGRES_PASSWORD_FILE':(target/'admin.txt').as_posix(),
            'DEVPLM_PG_DATA':data.as_posix(),'DEVPLM_DB_NAME':'devplm','DEVPLM_DB_HOST':'127.0.0.1','DEVPLM_DB_PORT':'55432',
            'DEVPLM_DB_ADMIN_USER':'postgres','DEVPLM_DB_API_USER':'devplm_api_login','DEVPLM_DB_SYNC_USER':'devplm_sync_login',
            'DEVPLM_ACCOUNTS_FILE':(local/'accounts.json').as_posix()}
        with (ROOT/'.env').open('x',encoding='utf-8') as handle:
            for key,value in values.items():handle.write(key+'='+value+'\n')
        return {'ok':True,'registered_credentials':len(refs),'secret_values_printed':False,'database_started':False}
    finally:lock.unlink()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--initialize',action='store_true');parser.add_argument('--data-directory',type=Path,required=True)
    args=parser.parse_args()
    if not args.initialize:parser.error('Explicit --initialize is required')
    try:print(json.dumps(initialize(args.data_directory)));return 0
    except Exception as exc:print(json.dumps({'ok':False,'error_type':type(exc).__name__,'message':'Setup incomplete; inspect local state before retrying. No credentials printed.'}));return 1

if __name__=='__main__':raise SystemExit(main())
