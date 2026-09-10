"""Create a NEW, history-free public source snapshot. No GitHub calls or git push.

Only reviewed code folders and approved project IDs are copied. The original
repository and its history are never removed or changed by this command.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.check_publish_safety import inspect_tree,read_policy

ROOT_FILES=['build.py','requirements.txt','publication-policy.json','.gitignore','.gitattributes','.env.example','docker-compose.yml']
FOLDERS=['src','tools','tests','backend','vendor']
EXCLUDED={'__pycache__','.pytest_cache','.work','.local','.git','.venv','collaboration-exports'}
PRIVATE_FILES={'tests/browser_navigation.js','tests/live_workbench_browser.cjs',
    'projects/dev-plm/requirements/REQ-20260910-d1ee5396.md',
    *{'projects/dev-plm/records/DEV-LOG-00'+str(i)+'.md' for i in (4,5,6)}}


def prepare(destination,root=ROOT):
    destination=Path(destination).resolve();root=Path(root).resolve()
    if destination.exists() or destination.is_relative_to(root):
        raise ValueError('Use a new destination outside the original repository; no overwrite is allowed')
    policy=read_policy(root/'publication-policy.json')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='devplm-public-stage-',dir=destination.parent) as temporary:
        stage=Path(temporary)
        files=[Path(p) for p in ROOT_FILES]
        files += [p.relative_to(root) for name in FOLDERS for p in (root/name).rglob('*') if p.is_file() and not (set(p.relative_to(root).parts)&EXCLUDED) and p.suffix not in {'.pyc'}]
        files += [Path('.github/workflows/pages.yml'),Path('fixtures/agent-demo.bundle'),Path('projects/governance.yaml'),Path('docs/publication.md'),Path('docs/data-model.md'),Path('docs/public-readme.md')]
        for pid in policy['projects']:
            files += [p.relative_to(root) for p in (root/'projects'/pid).rglob('*') if p.is_file() and not (set(p.relative_to(root).parts)&EXCLUDED)]
        for relative in files:
            if relative.as_posix() in PRIVATE_FILES:continue
            source=root/relative
            if not source.resolve().is_relative_to(root) or source.is_symlink():raise ValueError('Source symlink/out-of-scope file rejected')
            target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        shutil.copyfile(root/'docs/public-readme.md',stage/'README.md')
        for name in ['LICENSE']:
            if (root/name).is_file():shutil.copyfile(root/name,stage/name)
        (stage/'AGENTS.md').write_text('''# Development guide

Read README.md and STATUS.md first. Project facts live in projects/; private sources and credentials must stay outside public inputs. Keep secrets out of code, logs and screenshots.

Frontend source: src/ for offline views; backend/web/ for the private workbench. Do not hand-edit generated site/. Use explicit public data roots for public builds. Run relevant tests after changes.

Runtime logs and project documents are read-only views of explicitly authorized files. Do not broaden reader grants or source directories without authorization. Preserve existing user files and unrelated edits.
''',encoding='utf-8')
        (stage/'STATUS.md').write_text('Public source snapshot with fresh Git history. Includes offline views, a private FastAPI workbench, authorized live logs and project-document navigation. Private deployment data and production acceptance records are excluded. Optional maintenance is experimental and requires explicit local configuration.\n',encoding='utf-8')
        issues,_=inspect_tree(stage,policy,require_manifest=False)
        if issues:
            # Only safe checker excerpts are written; never a raw file dump.
            raise ValueError(json.dumps({'source_export_rejected':issues[:20]},ensure_ascii=False))
        manifest={'format':1,'purpose':'review-before-user-creates-public-repository','git_history_included':False,
            'published':False,'public_account':policy['public_account'],'project_ids':policy['projects'],
            'files':{p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.rglob('*')) if p.is_file()}}
        (stage/'PUBLIC_EXPORT.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        # A copy to a new destination; no existing user directory is replaced.
        shutil.copytree(stage,destination)
    return {'ok':True,'files':len(manifest['files'])+1,'git_history_included':False,'published':False}


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    try:result=prepare(args.destination)
    except (ValueError,OSError) as error:
        print(str(error));return 1
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
