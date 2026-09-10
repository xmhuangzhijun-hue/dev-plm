import json
import pytest
from backend import external_logs,project_documents as docs
from backend.protocol import Identity,ServiceError


def test_registered_documents_live_read_and_permissions(tmp_path,monkeypatch):
    source=tmp_path/'README.md';source.write_text('actual document')
    config=tmp_path/'mounts.json'
    config.write_text(json.dumps({'sources':[{'id':'q','name':'Q','directory':str(tmp_path),
        'readers':[{'tenant_id':'t','principal_id':'owner'}],
        'sections':{'overview':{'note':'source','documents':[{'title':'Readme','path':str(source)}]}}}]}))
    monkeypatch.setattr(external_logs,'CONFIG',config)
    actor=Identity('t','owner','owner')
    overview=docs.section(actor,'q','overview')
    assert len(overview['sections'])==9
    assert docs.section(actor,'q','ui')['items']==[]
    key=overview['items'][0]['key']
    first=docs.document(actor,'q',key)
    assert first['body']=='actual document'
    assert docs.document(actor,'q',key,first['revision'])['unchanged']
    source.write_text('updated document')
    assert docs.document(actor,'q',key,first['revision'])['body']=='updated document'
    with pytest.raises(ServiceError):docs.document(Identity('t','viewer','viewer'),'q',key)
    with pytest.raises(ServiceError):docs.document(actor,'q','../private')
    source.unlink()
    assert not docs.section(actor,'q','overview')['items'][0]['available']
    with pytest.raises(ServiceError):docs.document(actor,'q',key)
