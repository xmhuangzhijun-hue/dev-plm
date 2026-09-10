"""Read the authorized project's human-maintained records without a build or sync."""
from datetime import datetime, timezone
import hashlib
import json
import yaml


def read_logs(editor, actor, project_id, revision=None):
    _, directory = editor.scope(actor, project_id)
    folder = directory / 'records'
    entries, errors, signature = [], [], []
    if folder.is_symlink():
        return {'revision':'blocked','items':[], 'errors':['日志目录为链接，未读取。']}
    for file in sorted(folder.glob('*.md')):
        if file.is_symlink() or not file.resolve().is_relative_to(directory):
            errors.append({'path':file.name,'message':'链接文件未读取。'}); continue
        stat = file.stat()
        signature.append((file.name, stat.st_mtime_ns, stat.st_size))
        entries.append((file, stat))
    digest = hashlib.sha256(json.dumps([signature, errors], sort_keys=True).encode()).hexdigest()
    if revision == digest:
        return {'revision':digest,'unchanged':True}
    items = []
    for file, stat in entries:
        try:
            if stat.st_size > 256000: raise ValueError('日志超过256KB，请拆分记录。')
            text = file.read_text(encoding='utf-8-sig')
            parts = text.split('---', 2)
            if len(parts) != 3 or parts[0].strip(): raise ValueError('缺少日志元数据。')
            data = yaml.safe_load(parts[1])
            if not isinstance(data,dict): raise ValueError('日志元数据须为对象。')
            fields = {key:str(data.get(key,'') or '') for key in
                      ('id','title','time','stage','env','result','actor','before','after','target')}
            reqs = data.get('reqs',[])
            if not isinstance(reqs,list): raise ValueError('reqs须为列表。')
            items.append({**fields,'reqs':[str(r) for r in reqs], 'body':parts[2].strip(),
                          'path':'records/'+file.name,'modified_at':datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat()})
        except (ValueError, OSError, yaml.YAMLError):
            errors.append({'path':'records/'+file.name,'message':'格式或读取失败，请由记录者检查；其他日志仍可查看。'})
    items.sort(key=lambda item:item['modified_at'],reverse=True)
    return {'revision':digest,'items':items,'errors':errors,'checked_at':datetime.now(timezone.utc).isoformat()}
