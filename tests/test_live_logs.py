from types import SimpleNamespace
import pytest
from backend.live_logs import read_logs
from backend.protocol import ServiceError


def test_file_changes_appear_without_build(tmp_path):
    records=tmp_path/'records';records.mkdir()
    editor=SimpleNamespace(scope=lambda a,p:({},tmp_path))
    first=read_logs(editor,None,'p')
    path=records/'one.md'
    path.write_text('---\nid: ONE\ntitle: 首条日志\nstage: 测试\nenv: 本地\nreqs: [R1]\n---\n真实结果',encoding='utf-8')
    second=read_logs(editor,None,'p',first['revision'])
    assert second['items'][0]['body']=='真实结果'
    assert read_logs(editor,None,'p',second['revision'])['unchanged']
    path.write_text(path.read_text(encoding='utf-8')+'追加结果',encoding='utf-8')
    assert '追加结果' in read_logs(editor,None,'p',second['revision'])['items'][0]['body']
    path.unlink()
    assert read_logs(editor,None,'p')['items']==[]


def test_malformed_log_does_not_hide_valid_logs(tmp_path):
    records=tmp_path/'records';records.mkdir()
    (records/'bad.md').write_text('bad')
    (records/'good.md').write_text('---\nid: OK\n---\n<script>bad()</script>')
    result=read_logs(SimpleNamespace(scope=lambda a,p:({},tmp_path)),None,'p')
    assert len(result['errors'])==1
    assert result['items'][0]['id']=='OK'


def test_scope_checked_even_for_unchanged_request():
    def deny(a,p):raise ServiceError(404,'NOT_FOUND','not available')
    with pytest.raises(ServiceError):
        read_logs(SimpleNamespace(scope=deny),None,'unauthorized','known-revision')
