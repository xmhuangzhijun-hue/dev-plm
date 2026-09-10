import json
from pathlib import Path
import pytest
from backend import external_logs as logs
from backend.protocol import Identity,ServiceError


@pytest.fixture
def source(tmp_path,monkeypatch):
    root=tmp_path/'logs';root.mkdir()
    config=tmp_path/'sources.json'
    config.write_text(json.dumps({'sources':[{'id':'q','name':'Q','directory':str(root),
        'readers':[{'tenant_id':'t','principal_id':'owner'}]}]}))
    monkeypatch.setattr(logs,'CONFIG',config)
    return root,Identity('t','owner','owner')


def write(root,name='one.md',body='initial'):
    (root/name).write_text('---\nchange_id: C1\ndate: 2026-09-11\nwork_type: ops\noutcome: pending\n---\n# Actual log\n'+body,encoding='utf-8')


def test_existing_write_update_new_delete_without_sync(source):
    root,actor=source;write(root)
    first=logs.read(actor,'q');row=first['items'][0]
    assert not row['body'] and row['title']=='Actual log'
    assert logs.detail(actor,'q',row['record_key'])['body'].endswith('initial')
    assert logs.read(actor,'q',first['revision'])['unchanged']
    write(root,body='new content')
    second=logs.read(actor,'q',first['revision'])
    assert second['revision']!=first['revision']
    assert logs.detail(actor,'q',row['record_key'])['body'].endswith('new content')
    write(root,'two.md');assert len(logs.read(actor,'q')['items'])==2
    (root/'one.md').unlink();assert len(logs.read(actor,'q')['items'])==1


def test_identity_grant_is_not_tenant_wide(source):
    root,actor=source;write(root)
    for other in [Identity('t','other','owner'),Identity('other','owner','owner')]:
        assert logs.catalog(other)==[]
        with pytest.raises(ServiceError):logs.read(other,'q','known')
        with pytest.raises(ServiceError):logs.detail(other,'q','known')


def test_corruption_and_status_file_are_not_misreported(source):
    root,actor=source;write(root)
    (root/'bad.md').write_text('invalid')
    (root/'项目状态.md').write_text('not a session')
    result=logs.read(actor,'q')
    assert len(result['items'])==1 and len(result['errors'])==1
    with pytest.raises(ServiceError):logs.detail(actor,'q','../../secret')


def test_unchanged_metadata_uses_cache(source,monkeypatch):
    root,actor=source;write(root);logs.read(actor,'q')
    monkeypatch.setattr(logs,'parse',lambda f:(_ for _ in ()).throw(AssertionError('reparsed')))
    assert len(logs.read(actor,'q')['items'])==1
