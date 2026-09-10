from pathlib import Path
from types import SimpleNamespace
import pytest
from backend.protocol import Identity, ServiceError
from backend.source_editor import SourceEditor,sha

@pytest.fixture
def editor(tmp_path):
    root=tmp_path/'code';root.mkdir();directory=tmp_path/'sources'/'real';directory.mkdir(parents=True)
    (directory/'requirements').mkdir();(directory/'requirements/R.md').write_text('original',encoding='utf-8')
    def load():
        if (directory/'requirements/R.md').read_text(encoding='utf-8')=='INVALID':raise ValueError('invalid source')
        return {'project_directories':{'real':directory},'data_roots':[directory.parent],'source_sha256':'hash'}
    services=SimpleNamespace(list_projects=lambda actor:[{'id':'real','example':False}],workspace_loader=load,
        start_sync=lambda *args,**kwargs:{'state':'published'})
    return SourceEditor(services,root,publish=lambda w:None),Identity('tenant','owner','owner'),directory

def test_save_readback_idempotency_and_conflict(editor):
    e,actor,directory=editor;old=e.read(actor,'real','requirements/R.md')
    result=e.save(actor,'real','requirements/R.md','updated',old['revision'],'one')
    assert result['state']=='completed'
    assert e.read(actor,'real','requirements/R.md')['content']=='updated'
    assert e.save(actor,'real','requirements/R.md','updated',old['revision'],'one')==result
    with pytest.raises(ServiceError) as error:e.save(actor,'real','requirements/R.md','other',old['revision'],'two')
    assert error.value.status==409
    assert e.history(actor,'real')[0]['after']==sha(b'updated')
    assert next((e.root/'.local/edits').glob('*/before.bin')).read_bytes()==b'original'

def test_failed_validation_restores_original(editor):
    e,actor,directory=editor
    with pytest.raises(ValueError):e.save(actor,'real','requirements/R.md','INVALID',sha(b'original'),'bad')
    assert (directory/'requirements/R.md').read_text()=='original'
    assert e.history(actor,'real')[0]['state']=='rolled_back'

def test_publish_failure_retries_without_duplicate_sync(editor):
    e,actor,directory=editor;calls=[]
    e.services.start_sync=lambda *a,**kw:(calls.append(1) or {'state':'published'})
    e.publish=lambda w:(_ for _ in ()).throw(OSError())
    with pytest.raises(ServiceError):e.save(actor,'real','requirements/R.md','updated',sha(b'original'),'publish')
    assert e.history(actor,'real')[0]['state']=='view_pending'
    e.publish=lambda w:None
    assert e.save(actor,'real','requirements/R.md','updated',sha(b'original'),'publish')['state']=='completed'
    assert calls==[1]

def test_uncertain_sync_preserves_source_and_retries_same_job(editor):
    e,actor,directory=editor;keys=[]
    def sync(*args,**kwargs):
        keys.append(args[2])
        if len(keys)==1:raise OSError('lost acknowledgement')
        return {'state':'published'}
    e.services.start_sync=sync
    with pytest.raises(ServiceError):e.save(actor,'real','requirements/R.md','updated',sha(b'original'),'uncertain')
    assert (directory/'requirements/R.md').read_text()=='updated'
    assert e.history(actor,'real')[0]['state']=='sync_pending'
    assert e.save(actor,'real','requirements/R.md','updated',sha(b'original'),'uncertain')['state']=='completed'
    assert keys[0]==keys[1]

@pytest.mark.parametrize('name',['../outside.md','requirements/../../outside.md','C:/secret.md','project.yaml','governance.yaml','.env','collaboration-exports/one/data.json','requirements\\R.md'])
def test_disallowed_file_paths(editor,name):
    e,actor,directory=editor
    with pytest.raises(ServiceError):e.read(actor,'real',name)

def test_viewer_and_other_project_are_blocked(editor):
    e,actor,directory=editor
    with pytest.raises(ServiceError):e.save(Identity('tenant','viewer','viewer'),'real','requirements/R.md','x',sha(b'original'),'x')
    with pytest.raises(ServiceError):e.read(actor,'other','requirements/R.md')

def test_new_requirement_is_created_once(editor):
    e,actor,directory=editor
    result=e.save(actor,'real','requirements/NEW.md','new',None,'new')
    assert e.save(actor,'real','requirements/NEW.md','new',None,'new')==result
    assert (directory/'requirements/NEW.md').read_text()=='new'
