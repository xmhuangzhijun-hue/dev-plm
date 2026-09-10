"""External source roots use the same parser as offline and database consumers."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

import build
from tools.workspace_sources import resolve_data_roots


@pytest.fixture
def external_workspace(tmp_path, monkeypatch):
    # pytest's system temporary directory is deliberately outside the code repo.
    assert not tmp_path.resolve().is_relative_to(build.ROOT.resolve())
    monkeypatch.delenv('DEVPLM_DATA_ROOTS', raising=False)
    code = tmp_path / 'code'
    code.mkdir()
    shutil.copytree(build.ROOT / 'src', code / 'src')
    roots = [tmp_path / 'public-data', tmp_path / 'private-data']
    for data_root, name in zip(roots, ['qingdan', 'event-inbox']):
        shutil.copytree(build.ROOT / 'projects' / name, data_root / name)
    return code, roots


def project_data(root):
    text = (root / 'site/assets/project-data.js').read_text(encoding='utf-8')
    return json.loads(text.split('window.DEVPLM_DATA = ', 1)[1].strip().removesuffix(';'))


def write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')


def registrations(project_id, tenant_id='T-EXAMPLE', principal_id='P-EXAMPLE'):
    return {'tenants': [{'id': tenant_id, 'name': 'Explicit fictional test tenant'}],
            'principals': [{'id': principal_id, 'tenant_id': tenant_id, 'display_name': 'Fictional maintainer',
                            'actor_type': 'human', 'roles': ['maintainer']}],
            'project_tenants': {project_id: tenant_id}}


def test_root_precedence_environment_separator_and_duplicate_resolution(external_workspace, monkeypatch):
    code, roots = external_workspace
    default = code / 'projects'
    default.mkdir()
    assert resolve_data_roots(code) == (default.resolve(),)
    monkeypatch.setenv('DEVPLM_DATA_ROOTS', os.pathsep.join(map(str, roots)))
    assert resolve_data_roots(code) == tuple(path.resolve() for path in roots)
    assert resolve_data_roots(code, [roots[1], roots[1] / '.']) == (roots[1].resolve(),)
    with pytest.raises(ValueError, match='至少需要一个数据根'):
        resolve_data_roots(code, [])
    with pytest.raises(build.BuildError, match='数据根目录不存在'):
        build.load_workspace(code, [code / 'missing'])


def test_external_build_uses_relative_labels_and_internal_directory_map(external_workspace):
    code, roots = external_workspace
    workspace = build.load_workspace(code, data_roots=roots)
    assert set(workspace['project_directories']) == {'qingdan', 'event-inbox'}
    assert workspace['project_directories']['event-inbox'] == (roots[1] / 'event-inbox').resolve()
    assert 'qingdan/project.yaml' in workspace['documents']
    assert 'event-inbox/project.yaml' in workspace['documents']
    assert all(p['sourceDirectory'] == p['id'] for p in workspace['projects'])
    build.build(code, data_roots=roots)
    payload = project_data(code)
    serialized = json.dumps(payload, ensure_ascii=False)
    for root in roots:
        assert str(root) not in serialized and root.as_posix() not in serialized
    assert 'project_directories' not in serialized and 'data_roots' not in serialized
    assert {p['id'] for p in payload['projects']} == {'qingdan', 'event-inbox'}
    assert all(p['sourceDirectory'] == p['id'] for p in payload['projects'])


def test_stack_build_preserves_configured_roots(external_workspace):
    from tools.local_stack import build_command
    _, roots = external_workspace
    args = build_command({'DEVPLM_DATA_ROOTS': os.pathsep.join(map(str, roots))})
    assert args[2:] == ['--data-root', str(roots[0]), '--data-root', str(roots[1])]
    assert build_command({})[2:] == []


def test_live_site_removes_examples_without_deleting_source_projects(external_workspace):
    code, roots = external_workspace
    metadata = roots[1] / 'event-inbox/project.yaml'
    data = yaml.safe_load(metadata.read_text(encoding='utf-8'))
    data['example'] = False
    write_yaml(metadata, data)
    build.build(code, data_roots=roots)
    before = project_data(code)['build']['sourceSha256']
    (code / 'site-settings.json').write_text('{"include_examples": false}', encoding='utf-8')
    build.build(code, data_roots=roots)
    payload = project_data(code)
    assert [p['id'] for p in payload['projects']] == ['event-inbox']
    assert payload['build']['sourceSha256'] != before
    assert (roots[0] / 'qingdan/project.yaml').is_file()
    assert len(build.load_workspace(code, data_roots=roots)['projects']) == 2
    snapshot = (code / 'site/assets/project-data.js').read_bytes()
    (code / 'site-settings.json').write_text('{"include_examples": "false"}', encoding='utf-8')
    with pytest.raises(build.BuildError, match='include_examples'):
        build.build(code, data_roots=roots)
    assert (code / 'site/assets/project-data.js').read_bytes() == snapshot


def test_duplicate_project_id_fails_and_keeps_previous_site(external_workspace):
    code, roots = external_workspace
    build.build(code, data_roots=roots)
    output = code / 'site/assets/project-data.js'
    previous = output.read_bytes()
    shutil.copytree(roots[0] / 'qingdan', roots[1] / 'qingdan')
    with pytest.raises(build.BuildError, match='多数据根项目 id 冲突：qingdan'):
        build.build(code, data_roots=roots)
    assert output.read_bytes() == previous


def test_relocation_keeps_logical_fact_fingerprint(external_workspace, tmp_path):
    code, roots = external_workspace
    before = build.load_workspace(code, data_roots=roots)
    relocated = tmp_path / 'relocated'
    shutil.copytree(roots[0], relocated)
    after = build.load_workspace(code, data_roots=[relocated, roots[1]])
    assert before['source_sha256'] == after['source_sha256']
    assert before['documents'] == after['documents']


def test_governance_merges_identical_rows_and_preserves_original_sources(external_workspace):
    code, roots = external_workspace
    for root, name in zip(roots, ['qingdan', 'event-inbox']):
        write_yaml(root / 'governance.yaml', registrations(name))
    workspace = build.load_workspace(code, data_roots=roots)
    governance = workspace['governance']
    assert len(governance['tenants']) == len(governance['principals']) == 1
    assert governance['project_tenants'] == {'event-inbox': 'T-EXAMPLE', 'qingdan': 'T-EXAMPLE'}
    assert len(governance['sources']) == 2
    assert 'source' not in governance  # No invented merged raw source file.
    for group in ['tenants', 'principals']:
        row = governance[group][0]
        assert row['source'] in workspace['documents']
        assert row['source_pointer'] == f'/{group}/0'
    assert all(str(root) not in json.dumps(governance) for root in roots)


@pytest.mark.parametrize('conflict', ['tenant', 'principal', 'assignment'])
def test_governance_conflicts_fail_instead_of_overwriting(external_workspace, conflict):
    code, roots = external_workspace
    first = registrations('qingdan')
    second = registrations('event-inbox')
    if conflict == 'tenant':
        second['tenants'][0]['name'] = 'Conflicting name'
        message = '租户定义冲突'
    elif conflict == 'principal':
        second['principals'][0]['roles'] = ['viewer']
        message = '主体定义冲突'
    else:
        second['tenants'].append({'id': 'T-OTHER', 'name': 'Other fictional tenant'})
        second['project_tenants']['qingdan'] = 'T-OTHER'
        message = '项目租户归属冲突'
    write_yaml(roots[0] / 'governance.yaml', first)
    write_yaml(roots[1] / 'governance.yaml', second)
    with pytest.raises(build.BuildError, match=message):
        build.load_workspace(code, data_roots=roots)


def test_principal_ids_are_tenant_scoped_and_references_validate_after_merge(external_workspace):
    code, roots = external_workspace
    first = registrations('qingdan', 'T-ONE')
    second = registrations('event-inbox', 'T-TWO')
    # A principal may refer to a tenant registered by another configured root.
    first['principals'].append({'id': 'P-CROSS-ROOT', 'tenant_id': 'T-TWO', 'display_name': 'Fictional cross-root registration',
                                'actor_type': 'agent', 'roles': ['viewer']})
    write_yaml(roots[0] / 'governance.yaml', first)
    write_yaml(roots[1] / 'governance.yaml', second)
    workspace = build.load_workspace(code, data_roots=roots)
    assert len(workspace['governance']['principals']) == 3
    first['principals'][-1]['tenant_id'] = 'T-ABSENT'
    write_yaml(roots[0] / 'governance.yaml', first)
    with pytest.raises(build.BuildError, match='主体的租户不存在'):
        build.load_workspace(code, data_roots=roots)


def test_declared_project_owner_survives_merge_and_fact_projection(external_workspace):
    from backend.projection import prepare_rows, stable_pk
    code, roots = external_workspace
    first = registrations('qingdan', 'T-ONE', 'P-ONE')
    second = registrations('event-inbox', 'T-TWO', 'P-TWO')
    first['project_owners'] = {'qingdan': 'P-ONE'}
    # The same exact declaration may be repeated by a second root.
    second['project_owners'] = {'qingdan': 'P-ONE', 'event-inbox': 'P-TWO'}
    write_yaml(roots[0] / 'governance.yaml', first)
    write_yaml(roots[1] / 'governance.yaml', second)
    workspace = build.load_workspace(code, data_roots=roots)
    assert workspace['governance']['project_owners'] == {'event-inbox': 'P-TWO', 'qingdan': 'P-ONE'}
    assert workspace['governance']['project_owner_sources']['qingdan'] == '_roots/1/governance.yaml'
    assert workspace['governance']['project_owner_sources']['event-inbox'] == '_roots/2/governance.yaml'
    rows = prepare_rows(workspace)
    expected = {'qingdan': stable_pk('T-ONE', None, 'principals', 'P-ONE'),
                'event-inbox': stable_pk('T-TWO', None, 'principals', 'P-TWO')}
    assert {row['id']: row['owner_pk'] for row in rows['projects']} == expected
    # The declared owner is also preserved on project-scoped requirement facts.
    project_ids = {row['pk']: row['id'] for row in rows['projects']}
    assert all(row['owner_pk'] == expected[project_ids[row['project_pk']]] for row in rows['requirements'])


@pytest.mark.parametrize('invalid', ['cross_tenant', 'conflicting_owner', 'unknown_project'])
def test_invalid_project_owner_does_not_enter_projection(external_workspace, invalid):
    code, roots = external_workspace
    first = registrations('qingdan', 'T-ONE', 'P-ONE')
    second = registrations('event-inbox', 'T-TWO', 'P-TWO')
    if invalid == 'cross_tenant':
        first['project_owners'] = {'qingdan': 'P-TWO'}
        message = '所有者不存在或不属于项目租户'
    elif invalid == 'conflicting_owner':
        first['project_owners'] = {'qingdan': 'P-ONE'}
        second['project_owners'] = {'qingdan': 'P-TWO'}
        message = '项目所有者冲突'
    else:
        first['project_owners'] = {'absent-project': 'P-ONE'}
        message = 'project_owners 引用了不存在的项目'
    write_yaml(roots[0] / 'governance.yaml', first)
    write_yaml(roots[1] / 'governance.yaml', second)
    with pytest.raises(build.BuildError, match=message):
        build.load_workspace(code, data_roots=roots)


def test_external_tombstones_and_exports_have_distinct_authority(external_workspace):
    code, roots = external_workspace
    directory = roots[1] / 'event-inbox'
    write_yaml(directory / 'tombstones.yaml', [{'kind': 'requirements', 'id': 'REMOVED-DEMO',
               'deleted_at': '2026-09-05T12:00:00+08:00', 'data': {'id': 'REMOVED-DEMO', 'title': 'Explicit fictional tombstone'}}])
    before = build.load_workspace(code, data_roots=roots)
    assert before['tombstones'][0]['source'] == 'event-inbox/tombstones.yaml'
    assert before['tombstones'][0]['source'] in before['documents']
    export = directory / 'collaboration-exports/EXPORT-EXTERNAL-TEST'
    export.mkdir(parents=True)
    snapshot = {'project_id': 'event-inbox', 'export_id': export.name,
                'tables': {'discussions': [{'id': 'D-EXTERNAL', 'body': 'External root fictional discussion'}], 'claims': []}}
    raw = json.dumps(snapshot, ensure_ascii=False).encode('utf-8')
    (export / 'data.json').write_bytes(raw)
    manifest = {'schema_version': 1, 'authority': 'database-export', 'project_id': 'event-inbox',
                'export_id': export.name, 'created_at': '2026-09-05T12:00:00+08:00', 'state': 'completed',
                'files': [{'path': 'data.json', 'sha256': hashlib.sha256(raw).hexdigest()}]}
    (export / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    after = build.load_workspace(code, data_roots=roots)
    assert before['source_sha256'] == after['source_sha256']
    assert before['documents'] == after['documents']
    assert all(key.startswith('event-inbox/collaboration-exports/') for key in after['export_documents'])
    build.build(code, data_roots=roots)
    project = next(p for p in project_data(code)['projects'] if p['id'] == 'event-inbox')
    assert project['collaboration']['tables']['discussions'][0]['body'] == 'External root fictional discussion'
    assert any(f['path'].startswith('collaboration-exports/') for f in project['files'])
    assert all(not f['path'].startswith('collaboration-exports/') for p in after['projects'] for f in p['files'])


def test_code_entries_stay_relative_to_code_workspace(external_workspace):
    code, roots = external_workspace
    (code / 'entry.py').write_text('# Actual code-workspace entry\n', encoding='utf-8')
    meta_path = roots[0] / 'qingdan/project.yaml'
    meta = yaml.safe_load(meta_path.read_text(encoding='utf-8'))
    meta['code_entries'] = [{'id': 'CODE-EXTERNAL', 'title': 'Code entry', 'path': 'entry.py'}]
    write_yaml(meta_path, meta)
    workspace = build.load_workspace(code, data_roots=roots)
    project = next(p for p in workspace['projects'] if p['id'] == 'qingdan')
    assert project['codeFiles'][0]['content'] == '# Actual code-workspace entry\n'
    assert workspace['documents']['entry.py'] == '# Actual code-workspace entry\n'


def test_git_repo_is_resolved_from_actual_external_project(external_workspace, tmp_path):
    code, roots = external_workspace
    repo = tmp_path / 'history'
    repo.mkdir()
    def git(*args):
        result = subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True)
        return result.stdout.strip()
    git('init', '--quiet')
    (repo / 'fact.txt').write_text('Explicit fictional external-root Git evidence\n', encoding='utf-8')
    git('add', '--', 'fact.txt')
    git('-c', 'user.name=Fictional fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'Fictional external-root acceptance fixture')
    sha = git('rev-parse', 'HEAD')
    directory = roots[0] / 'qingdan'
    changes = directory / 'changes'
    changes.mkdir(exist_ok=True)
    (changes / 'CHG-EXTERNAL.md').write_text(f'---\nid: CHG-EXTERNAL\ntitle: Fictional external Git\nreqs: [DEMO-REQ-001]\nstatus: fictional-test\nrepo: ../../history\ncommit: {sha}\n---\nFictional test, not real project history.\n', encoding='utf-8')
    workspace = build.load_workspace(code, data_roots=roots)
    project = next(p for p in workspace['projects'] if p['id'] == 'qingdan')
    change = next(c for c in project['changes'] if c['id'] == 'CHG-EXTERNAL')
    assert change['git']['status'] == 'available'
    assert change['git']['commits'][0]['sha'] == sha
    assert change['git']['commits'][0]['files'][0]['path'] == 'fact.txt'


def test_cli_accepts_repeated_roots_and_environment(external_workspace):
    _, roots = external_workspace
    environment = dict(os.environ, DEVPLM_DATA_ROOTS=str(roots[1]))
    command = [sys.executable, str(build.ROOT / 'build.py'), '--check', '--data-root', str(roots[0]), '--data-root', str(roots[1])]
    explicit = subprocess.run(command, cwd=build.ROOT, env=environment, capture_output=True, text=True, encoding='utf-8')
    assert explicit.returncode == 0, explicit.stderr
    assert json.loads(explicit.stdout)['source_projects'] == 2
    inherited = subprocess.run(command[:3], cwd=build.ROOT, env=environment, capture_output=True, text=True, encoding='utf-8')
    assert inherited.returncode == 0, inherited.stderr
    assert json.loads(inherited.stdout)['source_projects'] == 1
