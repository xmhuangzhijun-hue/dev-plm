"""Start/stop this private stack. Never install/login Tailscale or enable Funnel."""
import argparse,hashlib,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
STATE=ROOT/'.local/stack.json'

def python_executable():
    path=Path(sys.executable)
    if path.name.lower()=='pythonw.exe':path=path.with_name('python.exe')
    return str(path)

def command(args):
    if Path(args[0]).stem.lower() in {'powershell','pwsh'} and '-Command' in args:
        args=list(args)
        index=args.index('-Command')+1
        args[index]='[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); '+args[index]
    result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:raise RuntimeError('Command failed: '+args[0]+' '+args[1]+'; inspect prerequisite status without exposing secrets')
    return result.stdout

def tailscale():
    location=shutil.which('tailscale') or str(Path(os.environ.get('ProgramFiles',''))/'Tailscale/tailscale.exe')
    if not Path(location).is_file():raise RuntimeError('Install and log in to Tailscale yourself first')
    state=json.loads(command([location,'status','--json']))
    if state.get('BackendState')!='Running':raise RuntimeError('Tailscale login is required; user must complete it')
    return location

def process_matches(state):
    pid=int(state['pid'])
    raw=command(['powershell','-NoProfile','-Command',f'Get-CimInstance Win32_Process -Filter "ProcessId = {pid}" | Select-Object ExecutablePath,CommandLine | ConvertTo-Json -Compress'])
    if not raw.strip():return False
    process=json.loads(raw)
    return Path(process.get('ExecutablePath','')).resolve()==Path(state['python']).resolve() and 'backend.private_site:app' in (process.get('CommandLine') or '') and '--port 8765' in (process.get('CommandLine') or '')

def build_command(env):
    args=[python_executable(),'build.py']
    for root in env.get('DEVPLM_DATA_ROOTS','').split(os.pathsep):
        if root:args.extend(['--data-root',root])
    return args

def launch_gateway(state):
    from backend.source_editor import atomic
    STATE.parent.mkdir(exist_ok=True)
    with (STATE.parent/'server.log').open('ab') as log:
        process=subprocess.Popen([python_executable(),'-m','uvicorn','backend.private_site:app','--host','127.0.0.1','--port','8765','--no-access-log','--log-level','warning'],cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    state.update(pid=process.pid,python=python_executable())
    atomic(STATE,json.dumps(state).encode())
    from urllib.request import urlopen
    for _ in range(60):
        if process.poll() is not None:raise RuntimeError('Backend exited; inspect local server log')
        try:
            with urlopen('http://127.0.0.1:8765/login',timeout=1) as response:
                if response.status==200:return state
        except OSError:time.sleep(.25)
    raise RuntimeError('Backend did not become ready')

def ensure():
    """Recover only this recorded stack; never replace unrelated port owners."""
    from backend.config import settings
    if not STATE.exists():raise RuntimeError('No owned stack state; initialize explicitly')
    state=json.loads(STATE.read_text(encoding='utf-8'))
    if not state.get('serve'):raise RuntimeError('Private Serve has not been initialized')
    try:command(['docker','info','--format','{{.ServerVersion}}'])
    except Exception:
        raise RuntimeError('Docker is unavailable; waiting for it without opening any app window') from None
    ts=tailscale();config=json.loads(command([ts,'serve','status','--json']))
    if hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()!=state.get('serve_config_sha256'):
        raise RuntimeError('Serve configuration changed; refusing to replace it')
    command(['docker','compose','up','-d','--wait','postgres'])
    if process_matches(state):
        from urllib.request import urlopen
        with urlopen('http://127.0.0.1:8765/login',timeout=5) as response:
            if response.status==200:return {'ok':True,'recovered':False}
        raise RuntimeError('Owned gateway is not healthy')
    with socket.socket() as probe:probe.bind(('127.0.0.1',8765))
    from backend.source_editor import workspace_lock,recover_prepared
    with workspace_lock(ROOT):
        if recover_prepared(ROOT,settings()):
            from tools.runtime_resources import available_memory_mb
            available=available_memory_mb()
            if available is None or available<2048:raise RuntimeError('Recovery needs 2GB free memory; deferred without rebuilding')
            command([python_executable(),'-m','backend.manage','sync'])
            command(build_command(settings()))
        launch_gateway(state)
    return {'ok':True,'recovered':True}

def stop():
    if not STATE.exists():return {'ok':True,'stopped':False,'reason':'No owned stack state; no other process stopped'}
    state=json.loads(STATE.read_text(encoding='utf-8'))
    if state.get('serve'):
        ts=tailscale();config=json.loads(command([ts,'serve','status','--json']))
        digest=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
        if digest!=state.get('serve_config_sha256'):raise RuntimeError('Serve configuration changed; refusing to alter concurrent service changes')
        command([ts,'serve','--https=8443','off'])
    if process_matches(state):
        # PID/command/executable verified together before terminating this process.
        command(['powershell','-NoProfile','-Command',f'Stop-Process -Id {int(state["pid"])} -ErrorAction Stop'])
    command(['docker','compose','stop','postgres'])
    STATE.unlink()
    return {'ok':True,'stopped':True,'data_retained':True}

def start(local_only=False):
    from backend.config import settings
    if STATE.exists():raise RuntimeError('Owned stack state exists; run status or stop before restarting')
    env=settings()
    data=Path(env.get('DEVPLM_PG_DATA','')).resolve()
    if data.drive.lower()!='d:' or not (data/'.devplm-owned').is_file():raise RuntimeError('Dedicated D-drive storage not initialized')
    if env.get('DEVPLM_DB_HOST')!='127.0.0.1':raise RuntimeError('Database must bind localhost')
    command(['docker','info','--format','{{.ServerVersion}}'])
    ts=None
    if not local_only:
        ts=tailscale()
        config=json.loads(command([ts,'serve','status','--json']))
        if '8443' in json.dumps(config):raise RuntimeError('Serve port 8443 already configured; no overwrite')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',8765))
    command(['docker','compose','up','-d','--wait','postgres'])
    command([sys.executable,'-m','backend.manage','migrate'])
    command([sys.executable,'-m','backend.manage','sync'])
    command(build_command(env))
    STATE.parent.mkdir(exist_ok=True)
    # Access logs disabled. Application logs stay local, never committed.
    with (STATE.parent/'server.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','backend.private_site:app','--host','127.0.0.1','--port','8765','--no-access-log','--log-level','warning'],cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    state={'pid':process.pid,'python':sys.executable,'serve':False}
    STATE.write_text(json.dumps(state),encoding='utf-8')
    from urllib.request import urlopen
    for _ in range(40):
        if process.poll() is not None:raise RuntimeError('Backend exited; inspect local server log')
        try:
            with urlopen('http://127.0.0.1:8765/login',timeout=1) as response:
                if response.status==200:break
        except OSError:time.sleep(.25)
    else:raise RuntimeError('Backend did not become ready; owned state retained for stop')
    if ts:
        command([ts,'serve','--bg','--https=8443','http://127.0.0.1:8765'])
        state['serve']=True
        state['serve_config_sha256']=hashlib.sha256(json.dumps(json.loads(command([ts,'serve','status','--json'])),sort_keys=True).encode()).hexdigest()
        STATE.write_text(json.dumps(state),encoding='utf-8')
    return {'ok':True,'backend':'loopback-only','database':'loopback-only','private_https':bool(ts),'phone_acceptance':'requires real device verification'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['start','stop','status','ensure']);parser.add_argument('--local-only',action='store_true',help='Local API checks only; browser login requires HTTPS via Serve')
    args=parser.parse_args()
    try:
        result=start(args.local_only) if args.action=='start' else stop() if args.action=='stop' else ensure() if args.action=='ensure' else {'state_exists':STATE.exists(),'process_owned':process_matches(json.loads(STATE.read_text())) if STATE.exists() else False}
        print(json.dumps(result));return 0
    except Exception as exc:print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__}));return 1

if __name__=='__main__':raise SystemExit(main())
