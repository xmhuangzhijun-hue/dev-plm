"""Explicit destructive recovery drill confined to its own newly named database.

Running without --run-explicit performs no file/DB/credential operation. The flag
is for the user-approved local command; this module never installs dependencies,
starts Docker, or drops the configured application database. The rebuilt test DB
and isolated offline site remain available for inspection after a completed run.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from . import db
from .capture_database import TABLES, assert_projection_equal, assert_schema, capture


@contextmanager
def temporary_settings(values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update({key: str(value) for key, value in values.items()})
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _write_json(path, value, exclusive=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if exclusive else 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(db.json_safe(value), handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def _relocate_references(value, original_directory):
    """Rewrite only path-reference fields in an already shared-parser-read object."""
    if isinstance(value, list):
        return [_relocate_references(item, original_directory) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in ('repo', 'local_path', 'history_repo', 'git_repo') and isinstance(item, str) and item and '://' not in item and not Path(item).is_absolute():
            result[key] = (original_directory / item).resolve().as_posix()
        else:
            result[key] = _relocate_references(item, original_directory)
    return result


def copy_sources(root, workspace, run_directory):
    """Copy only declared project directories/governance; never write originals."""
    import build
    import yaml
    code = run_directory / 'code'
    code.mkdir()
    for directory in ('src', 'tools'):
        shutil.copytree(root / directory, code / directory, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(root / 'build.py', code / 'build.py')
    for project in workspace['projects']:
        for entry in project.get('codeFiles', []):
            # load_workspace already validated each declared code path under root.
            relative = Path(entry['path'])
            source_file = (root / relative).resolve()
            target_file = (code / relative).resolve()
            if not source_file.is_relative_to(root.resolve()) or not target_file.is_relative_to(code.resolve()):
                raise ValueError('Declared code source escaped its code root')
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
    copied_roots = []
    original_roots = list(workspace['data_roots'])
    for i, original in enumerate(original_roots, 1):
        destination = run_directory / 'data' / ('root-' + str(i))
        destination.mkdir(parents=True)
        if (original / 'governance.yaml').is_file():
            shutil.copy2(original / 'governance.yaml', destination / 'governance.yaml')
        copied_roots.append(destination)
    for project in workspace['projects']:
        original = workspace['project_directories'][project['id']]
        matches = [i for i, source in enumerate(original_roots) if original.is_relative_to(source)]
        if len(matches) != 1:
            raise ValueError('Project must have exactly one source root for the drill')
        target = copied_roots[matches[0]] / project['id']
        shutil.copytree(original, target, ignore=shutil.ignore_patterns('collaboration-exports', '.git', '__pycache__'))
        paths = {'project.yaml', *(item['source'] for item in project.get('changes', []))}
        if (original / 'profile.yaml').is_file():
            paths.add('profile.yaml')
        for relative in paths:
            source_file = original / relative
            document = build.Document(source_file, original)
            replacement = _relocate_references(document.data, original)
            if replacement == document.data:
                continue
            text = yaml.safe_dump(replacement, allow_unicode=True, sort_keys=False)
            if source_file.suffix == '.md':
                text = '---\n' + text + '---\n\n' + document.body + '\n'
            (target / relative).write_text(text, encoding='utf-8')
    return code, copied_roots


def _database_identity(control, name):
    return control.execute('SELECT oid FROM pg_database WHERE datname=%s', (name,)).fetchone()


def recreate_owned_database(control, name, expected_oid):
    """Drop only the minted database after checking its exact name and live OID."""
    from psycopg import sql
    if not re.fullmatch(r'devplm_rebuild_[0-9a-f]{32}', name):
        raise ValueError('Disposable database name is invalid')
    current = _database_identity(control, name)
    if not current or current['oid'] != expected_oid:
        raise ValueError('Disposable database identity changed; refusing DROP')
    # No FORCE or termination of unknown sessions. An open user session fails safe.
    control.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
    if _database_identity(control, name) is not None:
        raise AssertionError('Database still exists after DROP')
    control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    recreated = _database_identity(control, name)
    if not recreated or recreated['oid'] == expected_oid:
        raise AssertionError('Fresh database has no distinct OID')
    return recreated['oid']


def _capture_phase(directory, phase, source_hash):
    with db.connection('admin') as conn:
        receipt = capture(conn, source_hash)
    assert_schema(receipt, empty=phase == 'empty')
    _write_json(directory / (phase + '.json'), receipt)
    return receipt


def _authenticated_actor(services, workspace, project_id):
    from .auth import Authentication
    from .config import account_bindings, secret
    tenant_id = workspace['governance']['project_tenants'][project_id]
    owners = {p['id'] for p in workspace['governance']['principals'] if p['tenant_id'] == tenant_id and p['roles'] == ['owner']}
    accounts = [a for a in account_bindings() if a.get('tenant_id') == tenant_id and a.get('principal_id') in owners]
    if not accounts:
        raise ValueError('The selected project requires an explicitly registered local owner login')
    account = sorted(accounts, key=lambda a: a['identifier'])[0]
    authentication = Authentication(services.resolve_identity)
    services.authentication = authentication
    credential = secret(account['credential_ref'])
    token = authentication.issue_token(account['identifier'], credential)['access_token']
    identity = authentication.authenticate(token)
    # Values are never serialized, printed, placed in command arguments or files.
    del credential, token
    return identity


def _permission_checks():
    from psycopg.errors import InsufficientPrivilege
    checks = [('api', 'UPDATE devplm.requirements SET title=title WHERE false'),
              ('api', 'DELETE FROM devplm.requirements WHERE false'),
              ('sync', 'UPDATE devplm.discussions SET title=title WHERE false')]
    for role, statement in checks:
        try:
            with db.connection(role) as conn:
                conn.execute(statement)
        except InsufficientPrivilege:
            continue
        raise AssertionError('Runtime role crossed its authority boundary: ' + role)
    return {'api_fact_update_denied': True, 'api_fact_delete_denied': True, 'sync_collaboration_update_denied': True}


def run(project_id='dev-plm', data_roots=None):
    import build
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from psycopg.rows import dict_row
    from .config import ROOT, get_database_url
    from .exports import restore
    from .manage import provision_logins
    from .services import Services

    run_id = uuid4().hex
    database_name = 'devplm_rebuild_' + run_id
    run_directory = ROOT / '.work' / ('rebuild-' + run_id)
    run_directory.mkdir(parents=True, exist_ok=False)
    phase = 'read_sources'
    try:
        original = build.load_workspace(ROOT, data_roots=data_roots)
        if project_id not in original['project_directories']:
            raise ValueError('The selected project is absent from the declared source roots')
        code, copied_roots = copy_sources(ROOT, original, run_directory)
        loader = lambda: build.load_workspace(code, data_roots=copied_roots)
        workspace = loader()
        source_hash = workspace['source_sha256']
        selected = next(p for p in workspace['projects'] if p['id'] == project_id)
        if not selected['requirements']:
            raise ValueError('The drill project needs a real file-backed requirement target')
        target_id = selected['requirements'][0]['id']
        control_dsn = make_conninfo(get_database_url('admin'), dbname='postgres')
        with psycopg.connect(control_dsn, autocommit=True, row_factory=dict_row) as control:
            phase = 'create_isolated_database'
            if _database_identity(control, database_name):
                raise ValueError('Minted database already exists; refusing reuse')
            control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database_name)))
            with temporary_settings({'DEVPLM_DB_NAME': database_name}):
                phase = 'migrate'
                with db.connection('admin') as conn:
                    first_migration = db.migrate(conn)
                    provision_logins(conn)
                    repeated_migration = db.migrate(conn)
                    if not first_migration['changed'] or repeated_migration['changed']:
                        raise AssertionError('Migration up is not repeatable')
                permissions = _permission_checks()
                phase = 'baseline'
                with db.connection('sync') as conn:
                    db.sync(conn, workspace)
                baseline = _capture_phase(run_directory, 'baseline', source_hash)
                for table in ('git_commits', 'git_file_changes', 'requirements', 'change_commits'):
                    if baseline['tables'][table]['count'] == 0:
                        raise AssertionError('The drill lacks actual file/Git coverage: ' + table)
                phase = 'repeated'
                with db.connection('sync') as conn:
                    repeated_sync = db.sync(conn, workspace)
                repeated = _capture_phase(run_directory, 'repeated', source_hash)
                assert_projection_equal(baseline, repeated)
                if not repeated_sync['unchanged']:
                    raise AssertionError('Repeated sync mutated F/G rows')
                phase = 'collaboration_and_export'
                services = Services(workspace_loader=loader)
                identity = _authenticated_actor(services, workspace, project_id)
                discussion = services.create_discussion(identity, project_id,
                    {'target_id': target_id, 'body': '数据库恢复演练首帖。此内容只写入本次隔离演练数据库和外置数据副本。'},
                    run_id + '-discussion', run_id + '-request-discussion')
                post = services.create_post(identity, discussion['id'],
                    {'body': '演练回复：验证原文、主体、时间、版本及审计能够通过普通文件恢复。', 'parent_post_id': None},
                    run_id + '-post', run_id + '-request-post')
                claim = services.create_claim(identity, project_id,
                    {'target_id': target_id, 'claimant_id': identity.principal_id},
                    run_id + '-claim', run_id + '-request-claim')
                exported = services.create_export(identity, project_id,
                    {'scope': ['discussions', 'claims', 'audit', 'notifications']},
                    run_id + '-export', run_id + '-request-export')
                if exported['state'] != 'completed':
                    raise AssertionError('Service export did not complete')
                with_export = loader()
                if with_export['source_sha256'] != source_hash:
                    raise AssertionError('D export contaminated the F/G source fingerprint')
                snapshot = with_export['collaboration_exports'][project_id]
                build.build(code, data_roots=copied_roots)
                with db.connection('sync') as conn:
                    db.sync(conn, with_export)
                after_export = _capture_phase(run_directory, 'after_export', source_hash)
                assert_projection_equal(baseline, after_export)
                phase = 'drop_and_recreate'
                recreated_oid = recreate_owned_database(control, database_name, baseline['database_oid'])
                with db.connection('admin') as conn:
                    db.migrate(conn)
                    if not db.migrate(conn, 'down')['changed']:
                        raise AssertionError('Migration down did not remove the isolated schema')
                    if db.migrate(conn, 'down')['changed']:
                        raise AssertionError('Repeated migration down was not a no-op')
                    db.migrate(conn)
                empty = _capture_phase(run_directory, 'empty', source_hash)
                if empty['database_oid'] != recreated_oid:
                    raise AssertionError('Empty capture is not the recreated database')
                phase = 'restore_file_facts'
                rebuilt_sources = loader()
                if rebuilt_sources['source_sha256'] != source_hash:
                    raise AssertionError('Source changed during the recovery drill')
                with db.connection('sync') as conn:
                    db.sync(conn, rebuilt_sources)
                phase = 'restore_collaboration'
                with db.connection('admin') as conn:
                    recovery = restore(conn, snapshot)
                with db.connection('admin') as conn:
                    repeated_recovery = restore(conn, snapshot)
                if not repeated_recovery['unchanged'] or repeated_recovery['inserted'] != 0:
                    raise AssertionError('Repeated D restore was not idempotent')
                restored = _capture_phase(run_directory, 'restored', source_hash)
                assert_projection_equal(baseline, restored)
                for table, rows in snapshot['tables'].items():
                    if restored['tables'][table]['count'] != len(rows):
                        raise AssertionError('D recovery does not match the exported high-water mark: ' + table)
                # Read through the actual service layer after recovery, not just SQL counts.
                if services.get_discussion(identity, discussion['id'])['body'] != discussion['body']:
                    raise AssertionError('Recovered discussion cannot be read through Services')
                if services.get_post(identity, post['id'])['body'] != post['body']:
                    raise AssertionError('Recovered post cannot be read through Services')
                phase = 'write_receipt'
                receipts = {'baseline': baseline, 'repeated': repeated, 'after_export': after_export, 'empty': empty, 'restored': restored}
                summary = {'schema_version': 1, 'status': 'passed', 'executed_at': datetime.now(timezone.utc).isoformat(),
                    'run_id': run_id, 'database': database_name, 'database_oid_before': baseline['database_oid'],
                    'database_oid_after': recreated_oid, 'source_sha256': source_hash, 'model_table_count': len(TABLES),
                    'checks': {**permissions, 'repeat_migration_up': True, 'repeat_migration_down': True,
                        'repeat_sync_all_columns': True, 'export_did_not_change_facts': True, 'database_oid_changed': True,
                        'fresh_31_tables_empty': True, 'same_source_all_columns_restored': True,
                        'full_7D_restore': True, 'repeat_D_restore': True, 'service_readback': True},
                    'phases': {name: {'database_oid': value['database_oid'], 'tables': {table: {'count': data['count'], 'sha256': data['sha256']} for table, data in value['tables'].items()}} for name, value in receipts.items()},
                    'collaboration_recovery': {'counts': recovery['counts'], 'digest': recovery['digest'],
                        'excludes_current_export_and_unfinished_ledger': True},
                    'browser_acceptance': 'not_run', 'test_database_retained': True,
                    'raw_receipts_directory': run_directory.relative_to(ROOT).as_posix(),
                    'offline_site': (code / 'site/index.html').relative_to(ROOT).as_posix()}
                receipt_path = ROOT / 'docs/rebuild-receipt.json'
                temp_receipt = run_directory / 'rebuild-receipt.json'
                _write_json(temp_receipt, summary)
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_receipt, receipt_path)
                return {'ok': True, 'database': database_name, 'receipt': 'docs/rebuild-receipt.json',
                    'raw_receipts_directory': summary['raw_receipts_directory'], 'offline_site': summary['offline_site'],
                    'browser_acceptance': 'not_run'}
    except Exception as exc:
        failure = {'ok': False, 'run_id': run_id, 'database': database_name, 'phase': phase,
                   'error_code': getattr(exc, 'code', 'REHEARSAL_FAILED'), 'error_type': type(exc).__name__,
                   'database_retained_if_created': True}
        _write_json(run_directory / 'failure.json', failure)
        return failure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-explicit', action='store_true', help='Execute the user-approved isolated create/drop/recovery drill')
    parser.add_argument('--project', default='dev-plm')
    parser.add_argument('--data-root', action='append', type=Path)
    args = parser.parse_args(argv)
    if not args.run_explicit:
        print(json.dumps({'ok': False, 'executed': False, 'required_flag': '--run-explicit'}, ensure_ascii=False))
        return 2
    try:
        result = run(args.project, args.data_root)
    except Exception as exc:
        # Connection errors can contain DSNs; never print exception text/tracebacks.
        result = {'ok': False, 'executed': False, 'error_code': getattr(exc, 'code', 'REHEARSAL_SETUP_FAILED'), 'error_type': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
