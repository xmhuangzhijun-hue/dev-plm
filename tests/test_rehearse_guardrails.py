"""No-DB checks for the explicit recovery command and isolated source copies."""
import json

import pytest
import yaml

from backend import rehearse


def test_no_flag_cannot_reach_the_runner(monkeypatch, capsys):
    monkeypatch.setattr(rehearse, 'run', lambda *_: pytest.fail('The runner must not execute without explicit flag'))
    assert rehearse.main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {'ok': False, 'executed': False, 'required_flag': '--run-explicit'}


def test_source_copy_preserves_originals_and_resolves_history_paths(tmp_path):
    root = tmp_path / 'code'
    root.mkdir()
    for name in ('src', 'tools', 'backend'):
        (root / name).mkdir()
        (root / name / 'entry.py').write_text('# actual source\n', encoding='utf-8')
    (root / 'build.py').write_text('# builder copy\n', encoding='utf-8')
    data_root = tmp_path / 'external-data'
    project = data_root / 'project-a'
    (project / 'changes').mkdir(parents=True)
    (project / 'collaboration-exports/old-export').mkdir(parents=True)
    (project / 'collaboration-exports/old-export/data.json').write_text('{}', encoding='utf-8')
    (data_root / 'governance.yaml').write_text('tenants: []\n', encoding='utf-8')
    (project / 'project.yaml').write_text('id: project-a\nrepo: https://code.example.invalid/project.git\nlocal_path: ../actual-repo\n', encoding='utf-8')
    (project / 'profile.yaml').write_text('history_repo: ../../history\nitems:\n- git_repo: ../fragment-history\n', encoding='utf-8')
    (project / 'changes/CHG-1.md').write_text('---\nid: CHG-1\nrepo: ../../history\n---\n\nOriginal narrative.\n', encoding='utf-8')
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    workspace = {'data_roots': (data_root,), 'project_directories': {'project-a': project},
        'projects': [{'id': 'project-a', 'changes': [{'source': 'changes/CHG-1.md'}],
                      'codeFiles': [{'path': 'backend/entry.py'}]}]}
    run = tmp_path / 'isolated-run'
    run.mkdir()
    code, copied_roots = rehearse.copy_sources(root, workspace, run)
    copied = copied_roots[0] / 'project-a'
    assert (code / 'backend/entry.py').read_text(encoding='utf-8') == '# actual source\n'
    assert not (copied / 'collaboration-exports').exists()
    assert before == {p.relative_to(project): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    meta = yaml.safe_load((copied / 'project.yaml').read_text(encoding='utf-8'))
    assert meta['repo'] == 'https://code.example.invalid/project.git'
    assert meta['local_path'] == (project / '../actual-repo').resolve().as_posix()
    profile = yaml.safe_load((copied / 'profile.yaml').read_text(encoding='utf-8'))
    assert profile['history_repo'] == (project / '../../history').resolve().as_posix()
    assert profile['items'][0]['git_repo'] == (project / '../fragment-history').resolve().as_posix()
    assert 'Original narrative.' in (copied / 'changes/CHG-1.md').read_text(encoding='utf-8')


def test_temporary_database_setting_is_restored(monkeypatch):
    import os
    monkeypatch.setenv('DEVPLM_DB_NAME', 'normal_database')
    with rehearse.temporary_settings({'DEVPLM_DB_NAME': 'devplm_rebuild_test'}):
        assert os.environ['DEVPLM_DB_NAME'] == 'devplm_rebuild_test'
    assert os.environ['DEVPLM_DB_NAME'] == 'normal_database'
