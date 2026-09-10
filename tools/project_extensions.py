"""File-owned common documents, typed master data and Git-only projections."""
from pathlib import Path

from tools.git_facts import extract_change
from tools.git_ancestry import annotate_history


def extend_project(p, directory, root, read, require, as_list, refs, locations):
    p['profile'] = {'groups': []}
    p['profileObjects'] = []
    locations['profileObjects'] = {}
    if p['type'] != 'software':
        profile = read('profile.yaml')
        require(profile, profile.data, ['groups'])
        groups = as_list(profile, profile.data['groups'], ('groups',))
        expected = {'agent': {'prompts', 'tools', 'memory', 'channels', 'permissions'},
                    'aigc': {'structure', 'prompts', 'assets', 'style'}}[p['type']]
        seen_groups = set()
        for i, group in enumerate(groups):
            ptr = ('groups', i)
            require(profile, group, ['id', 'title', 'objects'], ptr)
            if group['id'] in seen_groups or group['id'] not in expected:
                profile.fail('重复或不适用的 profile 分组', (*ptr, 'id'))
            seen_groups.add(group['id'])
            for j, obj in enumerate(as_list(profile, group['objects'], (*ptr, 'objects'))):
                op = (*ptr, 'objects', j)
                require(profile, obj, ['id'], op)
                if obj['id'] in locations['profileObjects']:
                    profile.fail('主数据 id 重复：' + obj['id'], (*op, 'id'))
                doc, pointer = profile, op
                if 'file' in obj:
                    path = (directory / obj['file']).resolve()
                    if not path.is_relative_to(directory.resolve()) or path.suffix != '.md':
                        profile.fail('片段文件必须位于本项目内且为 Markdown', (*op, 'file'))
                    doc = read(path.relative_to(directory.resolve()).as_posix())
                    require(doc, doc.data, ['id', 'title', 'reqs'])
                    if doc.data['id'] != obj['id']:
                        doc.fail('片段稳定 id 与 profile 引用不一致', ('id',))
                    if any(key in obj for key in ['title', 'reqs', 'content']):
                        profile.fail('片段内容只维护在 file，不能重复在 profile 中维护', op)
                    obj.update(doc.data, content=doc.body, source=obj['file'])
                    pointer = ()
                else:
                    require(profile, obj, ['title', 'reqs'], op)
                    obj['source'] = obj.get('source', 'profile.yaml')
                    referenced = (directory / obj['source']).resolve()
                    if not referenced.is_relative_to(directory.resolve()) or not referenced.is_file() or referenced.suffix not in ['.md', '.yaml', '.json']:
                        profile.fail('主数据 source 引用不存在或越过项目目录', (*op, 'source'))
                if p['type'] == 'agent' and group['id'] == 'prompts' and 'file' not in obj:
                    profile.fail('Agent 提示词必须分文件保存稳定片段', op)
                if 'git_path' in obj:
                    gp = Path(obj['git_path'])
                    if gp.is_absolute() or '..' in gp.parts or '\\' in obj['git_path']:
                        profile.fail('git_path 必须是仓库内使用 / 的相对文件路径', op)
                refs(doc, obj['reqs'], 'requirements', (*pointer, 'reqs'))
                obj['group'] = group['id']
                p['profileObjects'].append(obj)
                locations['profileObjects'][obj['id']] = (doc, pointer)
        if seen_groups != expected:
            profile.fail('缺少类型主数据分组：' + ', '.join(sorted(expected - seen_groups)), ('groups',))
        p['profile'] = profile.data

    for group in ['changes', 'releases', 'incidents', 'audits', 'reviews']:
        p[group] = []
        locations[group] = {}
        for path in sorted((directory / group).glob('*.md')):
            doc = read(path.relative_to(directory).as_posix())
            require(doc, doc.data, ['id', 'title', 'reqs', 'status'])
            obj = dict(doc.data, source=path.relative_to(directory).as_posix(), body=doc.body)
            if obj['id'] in locations[group]:
                doc.fail('重复编号：' + obj['id'], ('id',))
            refs(doc, obj['reqs'], 'requirements', ('reqs',))
            if group == 'changes':
                require(doc, obj, ['repo', 'commit'])
                commits = [obj['commit']] if isinstance(obj['commit'], str) else obj['commit']
                as_list(doc, commits, ('commit',))
                if any(not isinstance(sha, str) for sha in commits):
                    doc.fail('commit 应为 SHA 字符串或字符串列表', ('commit',))
                if obj['repo'] is not None and not isinstance(obj['repo'], str):
                    doc.fail('repo 应为本地路径字符串或 null', ('repo',))
                obj['git'] = extract_change(obj['repo'] or '', commits, directory)
            p[group].append(obj)
            locations[group][obj['id']] = (doc, ())

    def repo_key(value):
        path = Path(value or '')
        return str((path if path.is_absolute() else directory / path).resolve()).casefold()

    # History membership comes from Git paths in the configured repository.
    # Multiple documents can reference one commit without inflating its history.
    for obj in p['profileObjects']:
        obj['history'] = []
        path = obj.get('git_path')
        if not path:
            continue
        history_repo = obj.get('git_repo', p['profile'].get('history_repo'))
        if not isinstance(history_repo, str) or not history_repo:
            doc, pointer = locations['profileObjects'][obj['id']]
            doc.fail('有 git_path 的片段需要 profile.history_repo 或 git_repo 明确历史仓库', pointer)
        obj['history_repo'] = history_repo
        indexed = {}
        for change in p['changes']:
            if repo_key(change['repo']) != repo_key(history_repo):
                continue
            for commit in change['git'].get('commits', []):
                files = [f for f in commit.get('files', []) if path in [f.get('path'), f.get('old_path')]]
                if files:
                    if commit['sha'] in indexed:
                        h = indexed[commit['sha']]
                        h['changes'].append(change['id'])
                        h['reqs'] = list(dict.fromkeys(h['reqs'] + change['reqs']))
                    else:
                        h = {'change': change['id'], 'changes': [change['id']], 'reqs': list(change['reqs']),
                             'repo': history_repo, 'sha': commit['sha'], 'date': commit['date'],
                             'subject': commit['subject'], 'files': files}
                        indexed[commit['sha']] = h
                        obj['history'].append(h)
        proof = annotate_history(obj['history'], history_repo, directory)
        obj['history'] = proof['history']
        obj['history_ancestry'] = proof['ancestry']
    p['designFiles'] = [path.relative_to(directory).as_posix() for path in sorted((directory / 'design').glob('*.md'))]
    p['codeFiles'] = []
    meta = read('project.yaml')
    for i, entry in enumerate(as_list(meta, p.get('code_entries', []), ('code_entries',))):
        require(meta, entry, ['id', 'title', 'path'], ('code_entries', i))
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or path.suffix not in ['.py', '.js', '.html', '.css', '.md'] or any(part.startswith('.') for part in Path(entry['path']).parts):
            meta.fail('代码入口须指向工作台仓库内的可读源码文件', ('code_entries', i, 'path'))
        if any(f['id'] == entry['id'] for f in p['codeFiles']):
            meta.fail('重复代码入口 id', ('code_entries', i, 'id'))
        p['codeFiles'].append(dict(entry, content=path.read_text(encoding='utf-8-sig')))
