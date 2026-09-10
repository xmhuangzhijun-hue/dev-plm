"""Reproducible, entirely fictional external-private-root acceptance."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import build
from tools.check_publish_safety import inspect_tree,read_policy


def run():
    import yaml
    # A sibling of the code checkout, not an in-repository private-data folder.
    with tempfile.TemporaryDirectory(prefix='devplm-fictional-isolation-',dir=ROOT.parent) as temp:
        base=Path(temp);code=base/'code';private=base/'private-fixture'
        code.mkdir()
        for folder in ['src','projects','backend','tools']:
            shutil.copytree(ROOT/folder,code/folder,ignore=shutil.ignore_patterns('__pycache__','collaboration-exports'))
        shutil.copyfile(ROOT/'build.py',code/'build.py')
        shutil.copyfile(ROOT/'publication-policy.json',code/'publication-policy.json')
        pid='private-fixture-only';marker='FICTIONAL-EXTERNAL-CONTENT-ONLY'
        shutil.copytree(ROOT/'projects/event-inbox',private/pid)
        meta=private/pid/'project.yaml'
        data=yaml.safe_load(meta.read_text(encoding='utf-8'));data['id']=pid;data['description']=marker
        meta.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
        (private/'governance.yaml').write_text(yaml.safe_dump({'tenants':[],'principals':[],'project_tenants':{pid:'devplm-local'}}),encoding='utf-8')
        policy=read_policy(code/'publication-policy.json')
        public=build.build(code,data_roots=[code/'projects'],public_mode=True)
        assert not inspect_tree(code/'site',policy,[pid,marker,str(private),private.as_posix()])[0]
        first=(code/'site/assets/project-data.js').read_text(encoding='utf-8')
        assert pid not in first and marker not in first
        mixed=build.build(code,data_roots=[code/'projects',private])
        mixed_text=(code/'site/assets/project-data.js').read_text(encoding='utf-8')
        assert pid in mixed_text and marker in mixed_text
        assert str(private) not in mixed_text and private.as_posix() not in mixed_text
        assert inspect_tree(code/'site',policy,[pid,marker])[0]
        build.build(code,data_roots=[code/'projects'],public_mode=True)
        assert not inspect_tree(code/'site',policy,[pid,marker])[0]
        duplicate=base/'duplicate';shutil.copytree(ROOT/'projects/event-inbox',duplicate/'event-inbox')
        try:build.build(code,data_roots=[code/'projects',duplicate])
        except build.BuildError as exc:assert '冲突' in str(exc)
        else:raise AssertionError('Duplicate ID was not rejected')
        return {'ok':True,'fixture_is_fictional':True,'private_root_outside_repository':True,
            'public_projects':public['projects'],'merged_projects':mixed['projects'],
            'private_content_excluded_from_public':True,'merged_artifact_rejected':True,'id_collision_rejected':True}


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(run(),ensure_ascii=False,indent=2))
