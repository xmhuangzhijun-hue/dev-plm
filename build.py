#!/usr/bin/env python3
"""Read human-maintained project documents, validate, then publish an offline view."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

try:
    import yaml
except ImportError:
    raise SystemExit('缺少已约定依赖 PyYAML；请按 README 准备环境。本工具不会自动安装软件。')

ROOT = Path(__file__).resolve().parent
GENERATED = '本文件由 build.py 自动生成，请勿手工修改'


class BuildError(Exception):
    pass


class SourceLoader(yaml.SafeLoader):
    pass


SourceLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in rules if tag != 'tag:yaml.org,2002:timestamp']
    for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def unique_mapping(loader, node, deep=False):
    values = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in values:
            raise yaml.constructor.ConstructorError('重复字段', key_node.start_mark, str(key), key_node.start_mark)
        values[key] = loader.construct_object(value_node, deep=deep)
    return values


SourceLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


class Document:
    def __init__(self, path: Path, root: Path, plain=False, label_prefix=''):
        self.path, self.root = path, root
        relative = path.relative_to(root).as_posix()
        self.label = f'{label_prefix}/{relative}' if label_prefix else relative
        try:
            self.text = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError) as error:
            raise BuildError(f'{self.label}:1: 无法读取 UTF-8 文件：{error}') from error
        self.offset = 0
        self.body = ''
        raw = self.text
        if plain:
            self.data, self.node, self.body = {}, None, raw
            return
        if path.suffix == '.md':
            lines = raw.splitlines(keepends=True)
            if not lines or lines[0].strip() != '---':
                raise BuildError(f'{self.label}:1: 需要以 YAML frontmatter 开头')
            end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
            if end is None:
                raise BuildError(f'{self.label}:1: frontmatter 缺少结束标记')
            raw = ''.join(lines[1:end])
            self.body = ''.join(lines[end + 1:]).strip()
            self.offset = 1
        try:
            # JSON parsing is authoritative; YAML nodes only provide source locations.
            self.data = json.loads(raw) if path.suffix == '.json' else yaml.load(raw, Loader=SourceLoader)
            self.node = yaml.compose(raw, Loader=SourceLoader)
        except json.JSONDecodeError as error:
            raise BuildError(f'{self.label}:{error.lineno}: JSON 格式错误：{error.msg}') from error
        except yaml.YAMLError as error:
            mark = getattr(error, 'problem_mark', None)
            line = self.offset + (mark.line + 1 if mark else 1)
            raise BuildError(f'{self.label}:{line}: YAML 格式错误：{getattr(error, "problem", str(error))}') from error

    def line(self, pointer=()):
        node = self.node
        for part in pointer:
            if isinstance(node, yaml.MappingNode):
                next_node = next((value for key, value in node.value if key.value == str(part)), None)
            elif isinstance(node, yaml.SequenceNode) and str(part).isdigit():
                index = int(part)
                next_node = node.value[index] if index < len(node.value) else None
            else:
                next_node = None
            if next_node is None:
                break
            node = next_node
        return self.offset + (node.start_mark.line + 1 if node else 1)

    def fail(self, message, pointer=()):
        raise BuildError(f'{self.label}:{self.line(pointer)}: {message}')


def require(doc, data, names, prefix=()):
    if not isinstance(data, dict):
        doc.fail('应为对象', prefix)
    for name in names:
        if name not in data:
            doc.fail(f'缺少必填字段 {name}', (*prefix, name))


def as_list(doc, value, pointer=()):
    if not isinstance(value, list):
        doc.fail('应为列表', pointer)
    return value


def section(body, title):
    ending = r'(?=^##[ \t]+当前理解[ \t]*\r?$|\Z)' if title == '用户原话' else r'\Z'
    match = re.search(r'^##[ \t]+' + re.escape(title) + r'[ \t]*\r?\n(.*?)' + ending, body, re.M | re.S)
    # Preserve the source wording; remove only Markdown section separators.
    if not match:
        return None
    text = match.group(1).strip('\r\n')
    lines = text.split('\n')
    if title == '用户原话' and lines and all(line.startswith('>') for line in lines):
        return '\n'.join(line[2:] if line.startswith('> ') else line[1:] for line in lines)
    return text


def resolve_local(document, ref):
    if not ref.startswith('#/'):
        raise ValueError('仅支持本文件 JSON Pointer 引用；外部引用须先离线打包')
    node = document
    for part in ref[2:].split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node


def dereference(spec, obj):
    seen = set()
    while isinstance(obj, dict) and '$ref' in obj:
        ref = obj['$ref']
        if ref in seen:
            raise BuildError('引用对象存在循环：' + ref)
        seen.add(ref)
        obj = resolve_local(spec, ref)
    return obj


def example_values(spec, media, doc, pointer):
    examples = media.get('examples', {})
    if not isinstance(examples, dict):
        doc.fail('examples 应为命名示例对象', (*pointer, 'examples'))
    result = []
    for name, example in examples.items():
        if '$ref' in example:
            example = resolve_local(spec, example['$ref'])
        if 'externalValue' in example:
            doc.fail('离线站点不读取 externalValue；请把示例放在 examples.*.value', (*pointer, 'examples', name))
        if 'value' not in example:
            doc.fail('页面示例需要 examples.*.value', (*pointer, 'examples', name))
        result.append({'name': name, 'summary': example.get('summary', name), 'value': example['value']})
    return result


def load_project(directory: Path, root: Path, data_root: Path | None = None):
    docs = {}
    document_root = data_root if data_root is not None else root
    label_prefix = 'projects' if data_root is not None else ''

    def read(name):
        doc = Document(directory / name, document_root, label_prefix=label_prefix)
        docs[name] = doc
        return doc

    meta = read('project.yaml')
    require(meta, meta.data, ['id', 'name', 'description', 'stage', 'updated', 'type', 'kind', 'example', 'repo', 'branch', 'local_path', 'focus_requirement'])
    p = dict(meta.data)
    if p['id'] != directory.name or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', p['id']):
        meta.fail('项目 id 必须与目录名相同，只使用小写英文字母、数字和连字符', ('id',))
    if p['kind'] not in ['web', 'service']:
        meta.fail('kind 必须为 web 或 service', ('kind',))
    if p['type'] not in ['software', 'agent', 'aigc']:
        meta.fail('type 必须为 software、agent 或 aigc', ('type',))
    private_external = data_root is not None and not Path(data_root).resolve().is_relative_to(root.resolve())
    if not isinstance(p['example'], bool) or (not p['example'] and p['id'] != 'dev-plm' and not private_external):
        meta.fail('仓库内仅 dev-plm 自举允许真实项目；其他真实项目必须放在仓库外私有数据根', ('example',))
    p.update(screens=[], fields=[], apis=[], servers=[], errorCodes=[], contractVersion='', prototype={'kind': 'none', 'tasks': []}, onboarding=None)
    if p['type'] == 'software':
        onboarding = read('onboarding.yaml')
        require(onboarding, onboarding.data, ['frontend', 'backend', 'database', 'configuration', 'environments', 'owners'])
        p['onboarding'] = onboarding.data
        for side in ['frontend', 'backend']:
            require(onboarding, p['onboarding'][side], ['applicable'], (side,))
            if p['onboarding'][side]['applicable']:
                require(onboarding, p['onboarding'][side], ['language', 'framework', 'version', 'install', 'start', 'port'], (side,))
        if p['kind'] == 'service' and p['onboarding']['frontend']['applicable']:
            onboarding.fail('纯后端服务的 frontend.applicable 应为 false', ('frontend', 'applicable'))
        for i, config in enumerate(as_list(onboarding, p['onboarding']['configuration'], ('configuration',))):
            require(onboarding, config, ['name', 'purpose', 'source'], ('configuration', i))
            if any(k in config for k in ['value', 'default', 'secret', 'token', 'password']):
                onboarding.fail('配置只登记名称、用途与来源，不存放配置值或秘密', ('configuration', i))
        require(onboarding, p['onboarding']['database'], ['engine', 'start', 'migrate'], ('database',))
        for i, owner in enumerate(as_list(onboarding, p['onboarding']['owners'], ('owners',))):
            require(onboarding, owner, ['name', 'scope'], ('owners', i))

    p['contract'] = None
    p['requirements'], p['records'], p['tests'] = [], [], []
    locations = {key: {} for key in ['requirements', 'records', 'tests', 'screens', 'fields', 'apis']}
    for folder, group in [('requirements', 'requirements'), ('records', 'records'), ('tests', 'tests')]:
        for path in sorted((directory / folder).glob('*.md')):
            doc = read(path.relative_to(directory).as_posix())
            require(doc, doc.data, ['id', 'title'])
            item = dict(doc.data)
            if item['id'] in locations[group]:
                doc.fail(f'重复编号 {item["id"]}', ('id',))
            item['source'] = path.relative_to(directory).as_posix()
            if group == 'requirements':
                require(doc, item, ['status', 'priority', 'raised', 'updated', 'owner', 'version', 'next', 'steps', 'checks'])
                if len(as_list(doc, item['steps'], ('steps',))) != 7:
                    doc.fail('steps 应按页面中七个环节填写七项状态', ('steps',))
                for j, check in enumerate(as_list(doc, item['checks'], ('checks',))):
                    if not isinstance(check, list) or len(check) != 2 or not isinstance(check[0], str) or not isinstance(check[1], bool):
                        doc.fail('验收项应为 [描述, true/false]', ('checks', j))
                item['original'] = section(doc.body, '用户原话')
                item['understanding'] = section(doc.body, '当前理解')
                if item['original'] is None or item['understanding'] is None:
                    doc.fail('正文需要“## 用户原话”和“## 当前理解”')
            elif group == 'records':
                require(doc, item, ['time', 'stage', 'env', 'reqs', 'result', 'target', 'actor', 'before', 'after'])
                item['detail'] = doc.body
            else:
                require(doc, item, ['req', 'env', 'result', 'expected', 'actual', 'record'])
            p[group].append(item)
            locations[group][item['id']] = (doc, ())

    if p['type'] == 'software':
        for filename, group in [('ui/screens.yaml', 'screens'), ('data/fields.yaml', 'fields')]:
            doc = read(filename)
            p[group] = as_list(doc, doc.data)
            for i, item in enumerate(p[group]):
                require(doc, item, ['id', 'title' if group == 'screens' else 'name', 'reqs'], (i,))
                for derived in (['apis'] if group == 'screens' else ['screens', 'apis']):
                    if derived in item:
                        doc.fail(f'{derived} 是反向生成的关系，请只在 OpenAPI 或页面字段关系中维护', (i, derived))
                if item['id'] in locations[group]:
                    doc.fail(f'重复对象标识 {item["id"]}', (i, 'id'))
                item['source'] = filename
                locations[group][item['id']] = (doc, (i,))
        proto = read('ui/prototype.yaml')
        require(proto, proto.data, ['kind', 'tasks'])
        p['prototype'] = proto.data
        if p['kind'] == 'service' and p['screens']:
            read('ui/screens.yaml').fail('纯后端服务不应出现虚构 UI 页面')

        contract = read('api/openapi.json')
        spec = contract.data
        p['contract'] = spec
        # The official JSON Schema validator is kept as a small adapter in tools/.
        try:
            from tools.validate_openapi import validate_spec
        except ImportError as error:
            raise BuildError('缺少 jsonschema 或离线校验适配器；按 README 准备已约定依赖，不会自动安装。') from error
        errors = validate_spec(spec)
        if errors:
            raise BuildError('\n'.join(f'{contract.label}:{contract.line(error["path"])}: OpenAPI: {error["message"]}' for error in errors[:25]))
        p['servers'] = spec.get('servers', [])
        if len(p['servers']) < 3:
            contract.fail('示例契约至少需要开发、测试和生产三个 server', ('servers',))
        server_ids = {}
        for i, server in enumerate(p['servers']):
            key = server.get('x-environment')
            if not key or key in server_ids:
                contract.fail('server 需要唯一的 x-environment 标识', ('servers', i))
            server_ids[key] = server
        for i, env in enumerate(as_list(onboarding, p['onboarding']['environments'], ('environments',))):
            require(onboarding, env, ['id', 'label', 'server_ref'], ('environments', i))
            if env['server_ref'] not in server_ids:
                onboarding.fail(f'环境引用不存在：{env["server_ref"]}', ('environments', i, 'server_ref'))
            if 'url' in env or 'base_url' in env:
                onboarding.fail('环境地址只维护在 OpenAPI servers，这里只写 server_ref', ('environments', i))
            env['url'] = server_ids[env['server_ref']]['url']
        p['apis'] = []
        defined_tags = {tag['name'] for tag in spec.get('tags', [])}
        for api_path, path_item in spec.get('paths', {}).items():
            for method, operation in path_item.items():
                if method not in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace']:
                    continue
                pointer = ('paths', api_path, method)
                require(contract, operation, ['operationId', 'summary', 'tags', 'x-requirements'], pointer)
                aid = operation['operationId']
                if aid in locations['apis']:
                    contract.fail(f'重复 operationId {aid}', (*pointer, 'operationId'))
                for j, tag in enumerate(operation['tags']):
                    if tag not in defined_tags:
                        contract.fail(f'tag 未在根 tags 定义：{tag}', (*pointer, 'tags', j))
                requests, responses = [], []
                request_body = operation.get('requestBody', {})
                if '$ref' in request_body:
                    request_body = resolve_local(spec, request_body['$ref'])
                for mime, media in request_body.get('content', {}).items():
                    examples = example_values(spec, media, contract, (*pointer, 'requestBody', 'content', mime))
                    if not examples:
                        contract.fail('请求体缺少 examples', (*pointer, 'requestBody', 'content', mime))
                    requests.append({'mime': mime, 'examples': examples})
                for code, response in operation['responses'].items():
                    if '$ref' in response:
                        response = resolve_local(spec, response['$ref'])
                    samples = []
                    for mime, media in response.get('content', {}).items():
                        examples = example_values(spec, media, contract, (*pointer, 'responses', code, 'content', mime))
                        if str(code).startswith('2') and not examples:
                            contract.fail('主要响应缺少 examples', (*pointer, 'responses', code, 'content', mime))
                        samples.append({'mime': mime, 'examples': examples})
                    responses.append({'code': str(code), 'description': response['description'], 'samples': samples})
                parameters = {}
                for parameter in path_item.get('parameters', []) + operation.get('parameters', []):
                    resolved = dereference(spec, parameter)
                    parameters[(resolved['name'], resolved['in'])] = resolved
                a = {'id': aid, 'method': method.upper(), 'path': api_path, 'title': operation['summary'], 'description': operation.get('description', ''), 'reqs': operation['x-requirements'], 'screens': operation.get('x-screens', []), 'fields': operation.get('x-fields', []), 'tags': operation['tags'], 'parameters': list(parameters.values()), 'requestExamples': requests, 'responses': responses, 'security': operation.get('security', spec.get('security', [])), 'source': 'api/openapi.json'}
                p['apis'].append(a)
                locations['apis'][aid] = (contract, pointer)
        error_schema = spec.get('components', {}).get('schemas', {}).get('Error', {})
        enum = error_schema.get('properties', {}).get('code', {}).get('enum')
        descriptions = error_schema.get('x-code-descriptions', error_schema.get('properties', {}).get('code', {}).get('x-code-descriptions', {}))
        if not enum or any(code not in descriptions for code in enum):
            contract.fail('Error.code 需要 enum，且 x-code-descriptions 要说明每个错误码', ('components', 'schemas', 'Error'))
        p['errorCodes'] = [{'code': code, 'description': descriptions[code]} for code in enum]
        p['contractVersion'] = spec['info']['version']

    def refs(doc, values, destination, pointer):
        for index, value in enumerate(as_list(doc, values, pointer)):
            if value not in locations[destination]:
                doc.fail(f'引用不存在：{value}（目标类型 {destination}）', (*pointer, index))

    for group in ['screens', 'fields', 'apis', 'records']:
        for obj in p[group]:
            doc, pointer = locations[group][obj['id']]
            refs(doc, obj['reqs'], 'requirements', (*pointer, 'x-requirements' if group == 'apis' else 'reqs'))
            for name, destination in [('screens', 'screens'), ('fields', 'fields'), ('apis', 'apis')]:
                if name in obj:
                    refs(doc, obj[name], destination, (*pointer, 'x-' + name if group == 'apis' else name))
    for t in p['tests']:
        doc, pointer = locations['tests'][t['id']]
        if t['req'] not in locations['requirements']:
            doc.fail(f'引用不存在：{t["req"]}', ('req',))
        if t['record'] not in locations['records']:
            doc.fail(f'引用不存在：{t["record"]}', ('record',))
    from tools.project_extensions import extend_project
    extend_project(p, directory, root, read, require, as_list, refs, locations)
    groups = {'changes': 'changes', 'profile': 'profileObjects', 'releases': 'releases', 'incidents': 'incidents', 'audits': 'audits', 'reviews': 'reviews', 'requirements': 'requirements', 'screens': 'screens', 'data': 'fields', 'apis': 'apis', 'tests': 'tests', 'logs': 'records'}
    all_ids = set().union(*(set(index) for index in locations.values()))
    for record in p['records']:
        doc, _ = locations['records'][record['id']]
        target = record['target'].lstrip('#').split('/', 1)
        if target[0] in groups and (len(target) != 2 or target[1] not in locations[groups[target[0]]]):
            doc.fail(f'产物链接不存在：{record["target"]}', ('target',))
        if target[0] not in [*groups, 'impact', 'design', 'code', 'operations', 'development', 'onboarding', 'files']:
            doc.fail(f'未知目标视图：{record["target"]}', ('target',))
        if p['type'] != 'software' and target[0] in ['screens', 'data', 'apis', 'operations']:
            doc.fail('此项目类型没有对应的软件主数据视图', ('target',))
        if target[0] == 'impact' and len(target) == 2 and target[1] not in locations['requirements']:
            doc.fail('原话追溯页的需求引用不存在', ('target',))
        if target[0] == 'design' and (not p['designFiles'] or (len(target) == 2 and target[1] not in p['designFiles'])):
            doc.fail('设计文档引用不存在', ('target',))
        if target[0] == 'code' and (not p['codeFiles'] or (len(target) == 2 and target[1] not in {f['id'] for f in p['codeFiles']})):
            doc.fail('源码入口引用不存在', ('target',))
        if target[0] == 'files' and len(target) == 2:
            candidate = (directory / target[1]).resolve()
            if not candidate.is_relative_to(directory.resolve()) or not candidate.is_file() or candidate.suffix not in ['.md', '.yaml', '.yml', '.json']:
                doc.fail(f'文件引用不存在或越过项目目录：{record["target"]}', ('target',))
        if target[0] in ['operations', 'development'] and len(target) == 2 and target[1] not in locations['requirements']:
            doc.fail(f'视图的需求引用不存在：{target[1]}', ('target',))
        if record.get('parent') and record['parent'] not in all_ids:
            doc.fail(f'parent 引用不存在：{record["parent"]}', ('parent',))
    if p['focus_requirement'] not in locations['requirements']:
        meta.fail('focus_requirement 引用不存在', ('focus_requirement',))
    # The operation owns API-to-page / API-to-field associations. The page owns
    # page-to-field associations. Reverse lists are projections, never sources.
    for screen in p['screens']:
        screen['apis'] = [a['id'] for a in p['apis'] if screen['id'] in a['screens']]
    for field in p['fields']:
        field['screens'] = [s['id'] for s in p['screens'] if field['id'] in s.get('fields', [])]
        field['apis'] = [a['id'] for a in p['apis'] if field['id'] in a['fields']]
    for r in p['requirements']:
        for group in ['screens', 'fields', 'apis']:
            r[group] = [item['id'] for item in p[group] if r['id'] in item['reqs']]
    p['stages'] = list(dict.fromkeys(r['stage'] for r in p['records']))
    p['environments'] = list(dict.fromkeys(r['env'] for r in p['records']))
    for extra in sorted(directory.rglob('*')):
        if extra.is_file() and extra.suffix in ['.md', '.yaml', '.yml', '.json']:
            name = extra.relative_to(directory).as_posix()
            if name.startswith('collaboration-exports/'):
                continue  # D exports are read separately; never become F/G input.
            if name not in docs:
                docs[name] = Document(extra, document_root, plain=extra.suffix == '.md', label_prefix=label_prefix)
    p['files'] = [{'id': name, 'path': name, 'group': str(Path(name).parent).replace('\\', '/'), 'name': Path(name).name, 'content': doc.text} for name, doc in sorted(docs.items())]
    p['sourceDirectory'] = directory.relative_to(data_root or directory.parent).as_posix()
    return p, docs


def checked_child(path: Path, root: Path):
    resolved = path.resolve()
    if resolved == root.resolve() or not resolved.is_relative_to(root.resolve()):
        raise BuildError(f'拒绝操作生成目录之外的路径：{resolved}')
    return resolved


def load_workspace(root: Path = ROOT, data_roots=None):
    """The single parser shared by the offline builder and PostgreSQL sync."""
    root = root.resolve()
    from tools.workspace_sources import read_workspace_sources, resolve_data_roots
    try:
        roots = resolve_data_roots(root, data_roots)
    except ValueError as error:
        raise BuildError(str(error)) from error
    projects, documents = [], {}
    project_directories = {}

    def add_document(name, text):
        if name in documents and documents[name] != text:
            raise BuildError(f'{name}:1: 源码逻辑路径与项目资料冲突')
        documents[name] = text

    for root_index, data_root in enumerate(roots, 1):
        for directory in sorted(data_root.iterdir()):
            if not directory.is_dir() or directory.name.startswith('.'):
                continue
            if not directory.resolve().is_relative_to(data_root):
                raise BuildError(f'data-root[{root_index}]/{directory.name}:1: 项目目录越过数据根')
            if directory.name in project_directories:
                raise BuildError(f'data-root[{root_index}]/{directory.name}/project.yaml:1: 多数据根项目 id 冲突：{directory.name}')
            project, docs = load_project(directory, root, data_root=data_root)
            projects.append(project)
            project_directories[project['id']] = directory.resolve()
            for name, doc in docs.items():
                add_document(f'{project["sourceDirectory"]}/{name}', doc.text)
            for entry in project['codeFiles']:
                add_document(entry['path'], entry['content'])
    if not projects:
        raise BuildError('data-roots/:1: 至少需要一个项目')
    projects.sort(key=lambda p: (p['example'], p['id']))
    governance, tombstones, exports, export_documents, extra_documents = read_workspace_sources(
        root, projects, Document, require, as_list,
        data_roots=roots, project_directories=project_directories)
    documents.update(extra_documents)
    source_hash = hashlib.sha256(json.dumps(documents, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'projects': projects, 'documents': documents, 'source_sha256': source_hash,
            'governance': governance, 'tombstones': tombstones,
            'collaboration_exports': exports, 'export_documents': export_documents,
            # Server-only filesystem locations. build() never serializes these.
            'data_roots': roots, 'project_directories': project_directories}


def build(root: Path = ROOT, check_only=False, data_roots=None, public_mode=False, *, validated_workspace=None):
    root = root.resolve()
    workspace = validated_workspace if validated_workspace is not None else load_workspace(root, data_roots=data_roots)
    projects = workspace['projects']
    # Local presentation policy does not delete fixtures or collaboration data.
    # Public builds retain their separately reviewed publication policy.
    if not public_mode and (root / 'site-settings.json').exists():
        try:
            site_settings = json.loads((root / 'site-settings.json').read_text(encoding='utf-8'))
            if not isinstance(site_settings, dict) or type(site_settings.get('include_examples')) is not bool:
                raise ValueError()
        except (ValueError, TypeError):
            raise BuildError('site-settings.json:1: include_examples 必须为布尔值') from None
        if not site_settings['include_examples']:
            projects = [p for p in projects if not p['example']]
    if public_mode:
        from tools.publication import public_projects
        try:
            projects = public_projects(workspace, root)
        except ValueError as error:
            raise BuildError('publication-policy.json:1: ' + str(error)) from error
    documents = {**workspace['documents'], **workspace['export_documents']}
    if not public_mode and (root / 'site-settings.json').exists():
        documents['site-settings.json'] = (root / 'site-settings.json').read_text(encoding='utf-8')
    source_hash = hashlib.sha256(json.dumps(documents, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    for p in projects:
        p['collaboration'] = workspace['collaboration_exports'].get(p['id'])
        prefix = p['sourceDirectory'] + '/'
        for path, text in workspace['export_documents'].items():
            if path.startswith(prefix):
                name = path[len(prefix):]
                p['files'].append({'id': name, 'path': name, 'group': str(Path(name).parent).replace('\\', '/'), 'name': Path(name).name, 'content': text})
    summary = {'ok': True, 'projects': len(projects), 'source_projects': len(workspace['projects']), 'requirements': sum(len(p['requirements']) for p in projects), 'operations': sum(len(p['apis']) for p in projects), 'source_files': len(documents), 'source_sha256': source_hash}
    if check_only:
        return summary
    payload = {'projects': projects, 'build': {'sourceSha256': source_hash, 'sourceFiles': len(documents), 'gitSha256': hashlib.sha256(json.dumps([p['changes'] for p in projects], ensure_ascii=False, sort_keys=True).encode()).hexdigest(), 'publication': 'public' if public_mode else 'local'}}
    stage = checked_child(root / '.work' / 'site-stage', root / '.work')
    backup = checked_child(root / '.work' / 'site-previous', root / '.work')
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(root / 'src', stage)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (stage / 'assets' / 'project-data.js').write_text(f'/* {GENERATED} */\nwindow.DEVPLM_DATA = {serialized};\n', encoding='utf-8', newline='\n')
    if public_mode:
        (stage/'publication.json').write_text(json.dumps({'mode':'public','project_ids':[p['id'] for p in projects], 'source_sha256':source_hash},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path in stage.rglob('*'):
        if path.is_file() and path.suffix in ['.html', '.js', '.css'] and path.name != 'project-data.js':
            comment = f'<!-- {GENERATED} -->\n' if path.suffix == '.html' else f'/* {GENERATED} */\n'
            path.write_text(comment + path.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    (stage / 'assets' / '.gitattributes').write_text('project-data.js linguist-generated=true\n*.css linguist-generated=true\napp.js linguist-generated=true\n', encoding='utf-8')
    (stage / '.gitattributes').write_text('* linguist-generated=true\n', encoding='utf-8')
    site = checked_child(root / 'site', root)
    if backup.exists():
        shutil.rmtree(backup)
    if public_mode:
        from tools.check_publish_safety import inspect_tree, read_policy
        findings, _ = inspect_tree(stage, read_policy(root/'publication-policy.json'))
        if findings:
            first=findings[0]
            raise BuildError(f"{first['file']}:{first['line']}: 公开检查失败（{first['kind']}），共{len(findings)}处；候选在.work/site-stage，旧站保持。")
    if site.exists():
        os.replace(site, backup)
    try:
        os.replace(stage, site)
    except OSError:
        if backup.exists():
            os.replace(backup, site)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    summary['site'] = str(site / 'index.html')
    return summary


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='只校验文件，不更新 site/')
    parser.add_argument('--data-root', action='append', help='项目数据根，可重复；优先于 DEVPLM_DATA_ROOTS，默认 projects/')
    parser.add_argument('--public', action='store_true', help='仅公开数据根，明确裁剪历史显示并在替换site前执行发布检查')
    args = parser.parse_args()
    try:
        print(json.dumps(build(check_only=args.check, data_roots=args.data_root, public_mode=args.public), ensure_ascii=False, indent=2))
    except (BuildError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
