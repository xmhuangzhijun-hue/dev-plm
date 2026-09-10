"""Parse governance, explicit tombstones, and D-export snapshots once.

Database exports are kept outside the F/G fact input returned to synchronizers.
This module performs no database access and never writes project files.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path


def resolve_data_roots(root, data_roots=None, environ=None):
    """Resolve CLI/API roots, then environment roots, then the default.

    Relative explicit paths use the invoking process's working directory, as
    ordinary CLI paths do. Repeated spellings of the same resolved root load
    once. No filesystem locations from this result belong in public payloads.
    """
    if data_roots is None:
        environment = os.environ if environ is None else environ
        configured = environment.get('DEVPLM_DATA_ROOTS', '')
        data_roots = [value for value in configured.split(os.pathsep) if value] if configured else [Path(root) / 'projects']
    elif isinstance(data_roots, (str, os.PathLike)):
        data_roots = [data_roots]
    resolved, seen = [], set()
    for index, value in enumerate(data_roots, 1):
        if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
            raise ValueError(f'data-root[{index}]:1: 数据根必须是非空目录路径')
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f'data-root[{index}]:1: 数据根目录不存在或不是目录')
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            resolved.append(path)
    if not resolved:
        raise ValueError('data-roots/:1: 至少需要一个数据根')
    return tuple(resolved)


def merge_governance(roots, projects, Document, require, as_list):
    """Merge explicit registrations, retaining each row's original source.

    Tenant IDs are workspace-wide. Principal IDs are scoped to a tenant.
    Identical duplicate registrations are harmless; differing definitions or
    project assignments are errors. References are checked after all roots load.
    """
    documents, source_docs, tenants, principals, assignments, owners = {}, [], {}, {}, {}, {}
    for root_index, data_root in enumerate(roots, 1):
        path = data_root / 'governance.yaml'
        if not path.is_file():
            continue
        prefix = f'_roots/{root_index}' if len(roots) > 1 else ''
        doc = Document(path, data_root, label_prefix=prefix)
        require(doc, doc.data, ['tenants', 'principals', 'project_tenants'])
        governance = doc.data
        source_docs.append(doc)
        documents[doc.label] = doc.text
        local_tenants, local_principals = set(), set()
        for i, tenant in enumerate(as_list(doc, governance['tenants'], ('tenants',))):
            require(doc, tenant, ['id', 'name'], ('tenants', i))
            if not isinstance(tenant['id'], str) or not tenant['id']:
                doc.fail('租户编号必须为非空字符串', ('tenants', i, 'id'))
            if tenant['id'] in local_tenants:
                doc.fail('租户编号重复', ('tenants', i, 'id'))
            local_tenants.add(tenant['id'])
            if tenant['id'] in tenants and tenants[tenant['id']][0] != tenant:
                doc.fail('多数据根租户定义冲突：' + tenant['id'], ('tenants', i))
            tenants.setdefault(tenant['id'], (tenant, doc, i))
        for i, principal in enumerate(as_list(doc, governance['principals'], ('principals',))):
            require(doc, principal, ['id', 'tenant_id', 'display_name', 'actor_type', 'roles'], ('principals', i))
            if any(not isinstance(principal[name], str) or not principal[name] for name in ['id', 'tenant_id']):
                doc.fail('主体和租户编号必须为非空字符串', ('principals', i))
            key = (principal['tenant_id'], principal['id'])
            if key in local_principals:
                doc.fail('主体重复', ('principals', i))
            if principal['actor_type'] not in ['human', 'agent', 'service'] or any(role not in ['owner', 'maintainer', 'viewer'] for role in as_list(doc, principal['roles'], ('principals', i, 'roles'))):
                doc.fail('主体类型或角色不合法', ('principals', i))
            if len(principal['roles']) != 1:
                doc.fail('当前最小权限模型每个主体只设置一个角色', ('principals', i, 'roles'))
            if any(name in principal for name in ['password', 'credential', 'token', 'secret']):
                doc.fail('治理文件只保存非秘密身份与登记引用', ('principals', i))
            local_principals.add(key)
            if key in principals and principals[key][0] != principal:
                doc.fail('多数据根主体定义冲突：' + principal['id'], ('principals', i))
            principals.setdefault(key, (principal, doc, i))
        if not isinstance(governance['project_tenants'], dict):
            doc.fail('project_tenants 应为对象映射', ('project_tenants',))
        for project_id, tenant_id in governance['project_tenants'].items():
            if not isinstance(project_id, str) or not isinstance(tenant_id, str):
                doc.fail('项目及租户编号必须为字符串', ('project_tenants', project_id))
            if project_id in assignments and assignments[project_id][0] != tenant_id:
                doc.fail('多数据根项目租户归属冲突：' + project_id, ('project_tenants', project_id))
            assignments.setdefault(project_id, (tenant_id, doc))
        declared_owners = governance.get('project_owners', {})
        if not isinstance(declared_owners, dict):
            doc.fail('project_owners 应为对象映射', ('project_owners',))
        for project_id, principal_id in declared_owners.items():
            if any(not isinstance(value, str) or not value for value in (project_id, principal_id)):
                doc.fail('项目及所有者编号必须为非空字符串', ('project_owners', project_id))
            if project_id in owners and owners[project_id][0] != principal_id:
                doc.fail('多数据根项目所有者冲突：' + project_id, ('project_owners', project_id))
            owners.setdefault(project_id, (principal_id, doc))
    if not source_docs:
        return None, documents
    for (tenant_id, _), (_, doc, index) in principals.items():
        if tenant_id not in tenants:
            doc.fail('主体的租户不存在：' + tenant_id, ('principals', index, 'tenant_id'))
    project_ids = {p['id'] for p in projects}
    for project_id in sorted(project_ids):
        value = assignments.get(project_id)
        if value is None or value[0] not in tenants:
            (value[1] if value else source_docs[0]).fail('项目缺少有效的租户归属：' + project_id, ('project_tenants', project_id))
    for project_id, (_, doc) in assignments.items():
        if project_id not in project_ids:
            doc.fail('project_tenants 引用了不存在的项目：' + project_id, ('project_tenants', project_id))
    for project_id, (principal_id, doc) in owners.items():
        if project_id not in project_ids:
            doc.fail('project_owners 引用了不存在的项目：' + project_id, ('project_owners', project_id))
        if (assignments[project_id][0], principal_id) not in principals:
            doc.fail('项目所有者不存在或不属于项目租户：' + principal_id, ('project_owners', project_id))
    combined = {
        'tenants': [dict(value, source=doc.label, source_pointer=f'/tenants/{i}') for _, (value, doc, i) in sorted(tenants.items())],
        'principals': [dict(value, source=doc.label, source_pointer=f'/principals/{i}') for _, (value, doc, i) in sorted(principals.items())],
        'project_tenants': {key: value[0] for key, value in sorted(assignments.items())},
        'project_tenant_sources': {key: value[1].label for key, value in sorted(assignments.items())},
        'project_owners': {key: value[0] for key, value in sorted(owners.items())},
        'project_owner_sources': {key: value[1].label for key, value in sorted(owners.items())},
        'sources': [doc.label for doc in source_docs],
    }
    if len(source_docs) == 1:
        combined['source'] = source_docs[0].label
    return combined, documents


def read_workspace_sources(root, projects, Document, require, as_list, *, data_roots=None, project_directories=None):
    roots = resolve_data_roots(root, data_roots)
    governance, documents = merge_governance(roots, projects, Document, require, as_list)
    tombstones, exports, export_documents = [], {}, {}
    if project_directories is None:
        project_directories = {p['id']: next(data_root / p['id'] for data_root in roots if (data_root / p['id']).is_dir()) for p in projects}
    for project in projects:
        directory = project_directories[project['id']]
        source_prefix = project['sourceDirectory']
        path = directory / 'tombstones.yaml'
        if path.is_file():
            doc = Document(path, directory, label_prefix=source_prefix)
            for i, item in enumerate(as_list(doc, doc.data)):
                require(doc, item, ['kind', 'id', 'deleted_at', 'data'], (i,))
                if not isinstance(item['data'], dict) or item['data'].get('id') != item['id']:
                    doc.fail('墓碑 data 必须完整保留相同 id 的原对象', (i, 'data'))
                timestamp(doc, item['deleted_at'], (i, 'deleted_at'))
                tombstones.append(dict(item, project_id=project['id'], source=doc.label))
            documents[doc.label] = doc.text
        completed = []
        for manifest_path in sorted((directory / 'collaboration-exports').glob('*/manifest.json')):
            if manifest_path.parent.name.startswith('.'):
                continue
            manifest = Document(manifest_path, directory, label_prefix=source_prefix)
            data = manifest.data
            require(manifest, data, ['schema_version', 'authority', 'project_id', 'export_id', 'created_at', 'state', 'files'])
            if data['schema_version'] != 1 or data['authority'] != 'database-export' or data['project_id'] != project['id'] or data['export_id'] != manifest_path.parent.name:
                manifest.fail('协作导出身份或格式不匹配')
            if data['state'] != 'completed':
                manifest.fail('已发布的 manifest 必须标记 completed；未完成任务放入隐藏临时目录', ('state',))
            created_at = timestamp(manifest, data['created_at'], ('created_at',))
            files, seen = {}, set()
            for i, entry in enumerate(as_list(manifest, data['files'], ('files',))):
                require(manifest, entry, ['path', 'sha256'], ('files', i))
                target = (manifest_path.parent / entry['path']).resolve()
                if target in seen or not target.is_relative_to(manifest_path.parent.resolve()) or target == manifest_path.resolve() or not target.is_file() or target.suffix not in ['.json', '.md', '.yaml']:
                    manifest.fail('导出文件路径重复、不存在或越界', ('files', i, 'path'))
                raw = target.read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                    manifest.fail('协作导出文件校验失败：' + entry['path'], ('files', i, 'sha256'))
                try:
                    text = raw.decode('utf-8')
                except UnicodeDecodeError:
                    manifest.fail('导出文件必须为 UTF-8', ('files', i))
                seen.add(target)
                files[entry['path']] = text
                export_documents[f'{source_prefix}/{target.relative_to(directory).as_posix()}'] = text
            if 'data.json' not in files:
                manifest.fail('协作导出缺少 data.json', ('files',))
            try:
                snapshot = json.loads(files['data.json'])
            except ValueError:
                manifest.fail('协作导出 data.json 格式错误', ('files',))
            if snapshot.get('project_id') != project['id'] or snapshot.get('export_id') != data['export_id'] or not isinstance(snapshot.get('tables'), dict):
                manifest.fail('协作快照身份或 tables 不匹配', ('files',))
            allowed = {'discussions', 'discussion_posts', 'claims', 'notifications', 'idempotency_requests', 'collaboration_audit_events', 'collaboration_exports'}
            if set(snapshot['tables']) - allowed or any(not isinstance(rows, list) for rows in snapshot['tables'].values()):
                manifest.fail('协作快照包含非D级表或表内容不为列表', ('files',))
            export_documents[manifest.label] = manifest.text
            completed.append((created_at, data['export_id'], {**snapshot, 'manifest': data, 'source': manifest_path.relative_to(directory).as_posix()}))
        if completed:
            exports[project['id']] = sorted(completed, key=lambda x: (x[0], x[1]))[-1][2]
    return governance, tombstones, exports, export_documents, documents


def timestamp(doc, value, pointer):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('timezone required')
        return parsed.astimezone(dt.timezone.utc)
    except (ValueError, TypeError, AttributeError):
        doc.fail('时间必须为含时区的 ISO 8601', pointer)
