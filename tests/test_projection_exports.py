"""Pure projection and real file-publication checks; no PostgreSQL stand-in.

The snapshot query is replaced with explicit fixture rows only to exercise the
ordinary-file writer and the same reader used by the offline builder.
"""
import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

import build
from backend import exports
from backend.db import D_TABLES, DatabaseProblem
from backend.projection import SourcePayloadError, digest, prepare_rows, stable_pk


@pytest.fixture
def fixture_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv('DEVPLM_DATA_ROOTS', raising=False)
    code = tmp_path / 'code'
    data = tmp_path / 'external-data'
    code.mkdir()
    shutil.copytree(build.ROOT / 'src', code / 'src')
    shutil.copytree(build.ROOT / 'projects/qingdan', data / 'qingdan')
    governance = {
        'tenants': [{'id': 'T-TEST', 'name': 'Explicit test tenant'}],
        'principals': [{'id': 'P-TEST', 'tenant_id': 'T-TEST', 'display_name': 'Fixture owner',
                        'actor_type': 'human', 'roles': ['owner']}],
        'project_tenants': {'qingdan': 'T-TEST'},
    }
    (data / 'governance.yaml').write_text(yaml.safe_dump(governance), encoding='utf-8')
    return code, data


def test_projection_is_relocatable_and_rejects_export_ingestion(fixture_workspace, tmp_path):
    code, data = fixture_workspace
    before = build.load_workspace(code, [data])
    rows = prepare_rows(before)
    moved = tmp_path / 'moved-data'
    shutil.copytree(data, moved)
    after = build.load_workspace(code, [moved])
    assert digest(rows) == digest(prepare_rows(after))
    assert all(row['source_path'] in before['documents'] for values in rows.values() for row in values)
    contaminated = copy.deepcopy(before)
    contaminated['documents']['qingdan/collaboration-exports/E/data.json'] = '{}'
    with pytest.raises(SourcePayloadError, match='cannot enter'):
        prepare_rows(contaminated)
    missing = dict(before, governance=None)
    with pytest.raises(SourcePayloadError, match='explicitly declare'):
        prepare_rows(missing)


def test_export_roundtrips_shared_parser_without_changing_facts(fixture_workspace, monkeypatch):
    code, data = fixture_workspace
    before = build.load_workspace(code, [data])
    identity = {'tenant_id': 'T-TEST', 'principal_id': 'P-TEST', 'role': 'owner'}
    tpk = stable_pk('T-TEST', None, 'tenants', 'T-TEST')
    ppk = stable_pk('T-TEST', 'qingdan', 'projects', 'qingdan')
    apk = stable_pk('T-TEST', None, 'principals', 'P-TEST')
    tables = {table: [] for table in D_TABLES}
    tables['discussions'] = [{'pk': 'discussion-fixture', 'title': '首帖完整原文\n第二段保留。',
        'created_by': str(apk), 'created_at': '2026-09-05T00:00:00+00:00', 'revision': 2,
        'updated_at': '2026-09-05T01:00:00+00:00', 'target_pk': 'requirement-fixture', 'deleted_at': None}]
    labels = {'principals': {str(apk): {'id': 'P-TEST', 'display_name': 'Fixture owner'}},
              'objects': {'requirement-fixture': {'id': 'REQ-001', 'kind': 'requirements', 'title': '示例需求'}}}
    monkeypatch.setattr(exports, 'identity_rows', lambda *_: (tpk, ppk, apk, {}))
    monkeypatch.setattr(exports, '_snapshot_tables', lambda *_: {'tables': tables, 'labels': labels})
    directory = before['project_directories']['qingdan']
    receipt = exports.create_snapshot(None, identity, 'qingdan', 'EXP-TEST', directory, ['discussions'])
    after = build.load_workspace(code, [data])
    assert before['source_sha256'] == after['source_sha256']
    assert digest(prepare_rows(before)) == digest(prepare_rows(after))
    snapshot = after['collaboration_exports']['qingdan']
    assert set(snapshot['tables']) == set(D_TABLES)
    assert snapshot['labels'] == labels
    assert snapshot['tables']['discussions'][0]['title'] == '首帖完整原文\n第二段保留。'
    assert snapshot['manifest']['actual_tables'] == list(D_TABLES)
    assert snapshot['manifest']['exclusions']['current_export_id'] == 'EXP-TEST'
    assert all('/collaboration-exports/' in path for path in after['export_documents'])
    assert not list((directory / 'collaboration-exports').glob('.tmp-*'))
    assert exports.create_snapshot(None, identity, 'qingdan', 'EXP-TEST', directory, ['discussions']) == receipt
    with pytest.raises(DatabaseProblem, match='不一致'):
        exports.create_snapshot(None, identity, 'qingdan', 'EXP-TEST', directory, ['claims'])
    artifact = directory / 'collaboration-exports/EXP-TEST/discussions.md'
    artifact.write_text(artifact.read_text(encoding='utf-8') + 'tamper', encoding='utf-8')
    with pytest.raises(build.BuildError, match='校验失败'):
        build.load_workspace(code, [data])


def test_export_does_not_accept_request_path_or_viewer(tmp_path):
    owner = {'role': 'owner'}
    with pytest.raises(DatabaseProblem, match='非法路径'):
        exports.create_snapshot(None, owner, 'p', '../escape', tmp_path, ['discussions'])
    with pytest.raises(DatabaseProblem, match='viewer'):
        exports.create_snapshot(None, {'role': 'viewer'}, 'p', 'EXP', tmp_path, ['discussions'])
    assert not (tmp_path / 'collaboration-exports').exists()


def test_source_code_tombstone_retains_stable_target_and_full_object(fixture_workspace):
    code, data = fixture_workspace
    workspace = build.load_workspace(code, [data])
    project = workspace['projects'][0]
    original = {'id': 'code-proof', 'title': '保留代码来源', 'path': 'src/code-proof.py', 'content': '# retained source\n'}
    project['codeFiles'] = [original]
    workspace['documents'][original['path']] = original['content']
    before = prepare_rows(workspace)
    target = next(row for row in before['master_objects'] if row['id'] == 'code-proof')
    project['codeFiles'] = []
    workspace['documents'].pop(original['path'])
    workspace['documents']['qingdan/tombstones.yaml'] = 'ordinary explicit tombstone fixture'
    workspace['tombstones'] = [{'project_id': 'qingdan', 'kind': 'source_code', 'id': original['id'],
        'deleted_at': '2026-09-05T18:00:00+08:00', 'data': original, 'source': 'qingdan/tombstones.yaml'}]
    after = prepare_rows(workspace)
    retained = next(row for row in after['master_objects'] if row['id'] == 'code-proof')
    assert retained['pk'] == target['pk']
    assert retained['deleted_at'] is not None and retained['projection_state'] == 'stale'
    assert retained['payload']['content'] == original['content']
    assert retained['source_path'] == 'qingdan/tombstones.yaml'
    assert any(row['pk'] == target['pk'] and row['deleted_at'] is not None for row in after['object_registry'])
