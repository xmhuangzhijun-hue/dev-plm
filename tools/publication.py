"""Explicit public projection; never scrub arbitrary source text to pass a gate."""
import copy
from .check_publish_safety import read_policy


def public_projects(workspace, root):
    if tuple(workspace['data_roots']) != ((root/'projects').resolve(),):
        raise ValueError('公开模式只接受本代码仓库的 projects/；私有合并构建使用本地模式。')
    policy=read_policy(root/'publication-policy.json')
    projects=copy.deepcopy(workspace['projects'])
    if any(p['id'] not in policy['projects'] or (not p['example'] and p['id']!='dev-plm') for p in projects):
        raise ValueError('存在未审阅为公开样例的项目。')
    if workspace['collaboration_exports']:
        raise ValueError('公开数据根包含数据库协作导出；请移到私有根，不能公开。')
    for p in projects:
        if p['id']!='dev-plm':continue
        for change in p['changes']:
            facts=change['git']
            # Old repository history is retained locally. Even a currently safe
            # historical patch may embed earlier private data, so none is exposed.
            if facts.get('commits'):
                facts['reason']='公开版仅展示提交SHA、日期和客观文件统计；作者与历史补丁在本地保留。'
            for commit in facts.get('commits',[]):
                commit['author']='公开版未披露提交者'
                commit['subject']='历史提交（公开版不展开原提交说明）'
                for f in commit['files']:
                    f.update(patch='',hunks=[],publication_omitted=True,patch_available=False)
                    f.pop('patch_error',None)
            # Failed Git diagnostics can contain machine paths; the public notice
            # states the omission, without pretending the history was read.
            if facts.get('skipped'):
                facts['skipped']=[{'input':i.get('input',''),'reason':'公开版未包含本地Git诊断详情；请在本地查看。'} for i in facts['skipped']]
                if not facts.get('commits'):facts['reason']='指定历史在当前仓库不可读取；公开快照不包含原本地Git对象。'
    return projects
