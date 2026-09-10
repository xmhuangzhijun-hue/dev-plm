import copy
import json
from pathlib import Path
import shutil
from urllib.parse import quote

import pytest
import yaml
import build
from tools.check_publish_safety import inspect_tree,read_policy
from tools.verify_public_private import run


def scan(tmp_path,text,policy=None):
    (tmp_path/'sample.txt').write_text(text,encoding='utf-8')
    return inspect_tree(tmp_path,policy or read_policy(build.ROOT/'publication-policy.json'),require_manifest=False)[0]


@pytest.mark.parametrize('encoding',['plain','json','percent','unicode','html'])
def test_encoded_machine_paths_are_blocked(tmp_path,encoding):
    path='Z'+':/'+'fictional-home/private.txt'
    text={'plain':path,'json':json.dumps(path.replace('/','\\')),'percent':quote(path,safe=''),
          'unicode':''.join('\\u%04x'%ord(c) for c in path),'html':path.replace(':','&#58;')}[encoding]
    findings=scan(tmp_path,'heading\n'+text)
    assert any(i['kind']=='absolute_path' and i['line']==2 and i['file']=='sample.txt' for i in findings)


def test_names_registry_emails_private_inventory_and_secrets(tmp_path):
    identity=json.dumps({'ow'+'ner':'Fictional Unlisted Identity'})
    reference='SEC-'+'2099-'+'123'
    email='fictional-person'+'@'+'example.com'
    key='to'+'ken='+('fictionalvalue'*4)
    issues=scan(tmp_path,'\n'.join([identity,reference,email,key]))
    assert {'identity','credential_reference','email','credential_shape'} <= {i['kind'] for i in issues}
    assert 'fictionalvalue' not in json.dumps(issues)
    (tmp_path/'sample.txt').write_text('A PRIVATE-FIXTURE-TEXT marker',encoding='utf-8')
    assert inspect_tree(tmp_path,private_values=['PRIVATE-FIXTURE-TEXT'],require_manifest=False)[0]


def test_invalid_email_and_scoped_literal_allowlist(tmp_path):
    policy=read_policy(build.ROOT/'publication-policy.json')
    assert not scan(tmp_path,'fictional-person'+'@'+'example.invalid',policy)
    path='Z'+':/'+'fictional-home/public-example'
    policy['allowlist'].append({'file':'sample.txt','kind':'absolute_path','value':path,'reason':'This exact synthetic test path only'})
    assert not scan(tmp_path,path,policy)
    assert scan(tmp_path,path+'-different',policy)
    (tmp_path/'other.txt').write_text(path,encoding='utf-8')
    assert inspect_tree(tmp_path,policy,require_manifest=False)[0]


def test_fail_closed_missing_manifest_invalid_policy_binary(tmp_path):
    assert inspect_tree(tmp_path)[0]
    (tmp_path/'unknown.bin').write_bytes(bytes([0,255,1]))
    assert any(x['kind']=='uninspected_binary' for x in inspect_tree(tmp_path,require_manifest=False)[0])
    policy=read_policy(build.ROOT/'publication-policy.json')
    policy['allowlist'].append({'file':'*','kind':'absolute_path','value':'.*','reason':'invalid wildcard'})
    p=tmp_path/'policy.json';p.write_text(json.dumps(policy),encoding='utf-8')
    with pytest.raises(ValueError):read_policy(p)


def test_private_public_external_roots_and_id_conflict():
    assert run()['merged_projects']==6


def test_sensitive_source_injection_is_not_silently_scrubbed(tmp_path):
    code=tmp_path/'code';code.mkdir()
    for folder in ['src','projects','backend','tools']:
        shutil.copytree(build.ROOT/folder,code/folder,ignore=shutil.ignore_patterns('__pycache__','collaboration-exports'))
    shutil.copyfile(build.ROOT/'build.py',code/'build.py')
    shutil.copyfile(build.ROOT/'publication-policy.json',code/'publication-policy.json')
    build.build(code,data_roots=[code/'projects'],public_mode=True)
    before=(code/'site/assets/project-data.js').read_bytes()
    source=next((code/'projects/qingdan/requirements').glob('*.md'))
    original=source.read_text(encoding='utf-8')
    source.write_text(original+'\nInjected test path: '+('Z'+':/'+'fictional-private/record')+'\n',encoding='utf-8')
    with pytest.raises(build.BuildError,match='公开检查失败'):build.build(code,data_roots=[code/'projects'],public_mode=True)
    assert (code/'site/assets/project-data.js').read_bytes()==before
    issues,_=inspect_tree(code/'.work/site-stage')
    assert any(i['kind']=='absolute_path' and i['line']>0 and i['file']=='assets/project-data.js' for i in issues)
    source.write_text(original,encoding='utf-8')
    build.build(code,data_roots=[code/'projects'],public_mode=True)
    assert not inspect_tree(code/'site')[0]


def test_workflow_only_manual_gate_before_upload_and_deploy():
    data=yaml.safe_load((build.ROOT/'.github/workflows/pages.yml').read_text(encoding='utf-8'))
    assert set(data['on'])=={'workflow_dispatch'}
    steps=data['jobs']['build']['steps']
    gate=next(i for i,s in enumerate(steps) if 'tools/check_publish_safety.py' in s.get('run',''))
    upload=next(i for i,s in enumerate(steps) if 'upload-pages-artifact' in s.get('uses',''))
    assert gate<upload
    assert all(not s.get('continue-on-error') and 'always()' not in s.get('if','') for s in steps)
    assert data['jobs']['deploy']['needs']=='build'
    command=next(s['run'] for s in steps if 'build.py' in s.get('run',''))
    assert '--public --data-root projects' in command
    assert data['permissions']=={'contents':'read'}


def test_public_mode_rejects_external_roots_before_publish(tmp_path):
    from tools.publication import public_projects
    with pytest.raises(ValueError,match='projects'):
        public_projects({'data_roots':[tmp_path]},build.ROOT)
