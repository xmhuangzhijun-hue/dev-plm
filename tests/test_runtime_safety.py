from types import SimpleNamespace

from backend.services import Services
from tools import local_stack, maintenance, runtime_resources


def test_empty_exports_do_not_load_whole_workspace(tmp_path):
    service=Services(workspace_loader=lambda: (_ for _ in ()).throw(AssertionError('full parse')))
    service.source_roots=[tmp_path]
    service._exported={('claims','old',1)}
    service._refresh_export_coverage()
    assert service._exported==set()


def test_existing_export_retains_validation(tmp_path):
    file=tmp_path/'project/collaboration-exports/export/manifest.json'
    file.parent.mkdir(parents=True);file.write_text('{}')
    calls=[]
    service=Services(workspace_loader=lambda: calls.append(True) or {
        'project_directories':{'project':tmp_path/'project'},'collaboration_exports':{}})
    service.source_roots=[tmp_path]
    service._refresh_export_coverage()
    assert calls==[True]


def test_powershell_output_preserves_unicode_and_hides_window(monkeypatch):
    captured={}
    def run(args,**kwargs):
        captured.update(args=args,**kwargs)
        return SimpleNamespace(returncode=0,stdout='中文路径')
    monkeypatch.setattr(local_stack.subprocess,'run',run)
    assert local_stack.command(['powershell','-NoProfile','-Command','Get-Date'])=='中文路径'
    assert 'OutputEncoding' in captured['args'][-1]
    assert captured['encoding']=='utf-8'
    assert captured['creationflags']==getattr(local_stack.subprocess,'CREATE_NO_WINDOW',0)


def test_low_memory_cycle_starts_nothing(tmp_path,monkeypatch):
    monkeypatch.setattr(maintenance,'ROOT',tmp_path)
    monkeypatch.setattr(runtime_resources,'available_memory_mb',lambda:128)
    monkeypatch.setattr(local_stack,'ensure',lambda: (_ for _ in ()).throw(AssertionError('started service')))
    assert maintenance.cycle()['state']=='deferred'
