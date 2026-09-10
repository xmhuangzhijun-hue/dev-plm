"""Map the shared build loader's normalized objects to deterministic F/G rows.

This module never reads or parses project files, calls Git, writes files, or reads
collaboration exports. build.load_workspace owns parsing/validation/Git extraction.

Explicit tombstones cover ordinary requirements/changes/records/tests and their
screen/field/API/profile/source-document/source-code objects. Structural removal
of projects, tenants, principals, repository registrations, whole contracts and
environment declarations is not a generic tombstone operation in this version:
retain the corresponding file declaration while D data references it, or perform
a separately designed migration. Sync never invents retained database facts.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from uuid import UUID, uuid5

NAMESPACE=UUID('af81907c-f785-574f-9e2f-de5074b51b84')
PROJECTION_VERSION='devplm-facts-v1'
F_TABLES=('tenants','principals','projects','repositories','requirements','requirement_checks','changes',
 'change_requirements','change_commits','git_commits','git_file_changes','test_cases','releases','incidents',
 'security_audits','retrospectives','activity_records','api_contracts','environments','master_objects',
 'object_links','object_registry')
GROUP_TABLE={'requirements':'requirements','changes':'changes','records':'activity_records','tests':'test_cases',
 'releases':'releases','incidents':'incidents','audits':'security_audits','reviews':'retrospectives',
 'screens':'master_objects','fields':'master_objects','apis':'master_objects','profile':'master_objects',
 'source_document':'master_objects','source_code':'master_objects'}

class SourcePayloadError(ValueError):
    code='SOURCE_VALIDATION_FAILED'

def canonical(value):
    def convert(obj):
        if isinstance(obj,datetime): return obj.astimezone(timezone.utc).isoformat()
        if isinstance(obj,UUID): return str(obj)
        raise TypeError(type(obj).__name__)
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=convert)

def digest(value): return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()

def stable_pk(tenant_id,project_id,kind,object_id):
    return uuid5(NAMESPACE,canonical([str(tenant_id),str(project_id or ''),str(kind),str(object_id)]))

def timestamp(value):
    # Incomplete historic labels are retained in source_data, not invented as dates.
    if not isinstance(value,str) or not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',value): return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone(timedelta(hours=8)))
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None

def prepare_rows(payload):
    """Return {table: [row]} from the shared loader output, without side effects."""
    required={'projects','documents','source_sha256','governance','tombstones'}
    if not required<=payload.keys(): raise SourcePayloadError('Shared loader payload lacks '+','.join(sorted(required-payload.keys())))
    docs=payload['documents']
    if any('/collaboration-exports/' in '/'+str(path).replace('\\','/') for path in docs):
        raise SourcePayloadError('D collaboration exports cannot enter the F/G source document map')
    gov=payload['governance']
    if not isinstance(gov,dict) or not all(k in gov for k in ('tenants','principals','project_tenants')):
        raise SourcePayloadError('Governance must explicitly declare tenants, principals, project_tenants')
    tenants={str(t['id']):t for t in gov['tenants']}
    principals={(str(p['tenant_id']),str(p['id'])):p for p in gov['principals']}
    projects={str(p['id']):copy.deepcopy(p) for p in payload['projects']}
    prefixes={pid:str(p['sourceDirectory']).rstrip('/')+'/' for pid,p in projects.items()}
    rows={t:{} for t in F_TABLES}
    epoch=payload['source_sha256']
    project_tenants=gov['project_tenants']
    owners=gov.get('project_owners',{})
    source_gov=gov.get('source')

    def owner_pk(tenant_id,project_id,obj):
        owner=obj.get('owner_id') or owners.get(project_id)
        if owner is None: return None
        if (tenant_id,str(owner)) not in principals:
            raise SourcePayloadError('Explicit owner is absent from governance principals')
        return stable_pk(tenant_id,None,'principals',owner)

    def add(table,tenant_id,project_id,oid,data,extra,source=None,pointer=None,kind=None,register=True):
        source=source or data.get('_tombstone_source') or data.get('source') or (prefixes[project_id]+'project.yaml' if project_id else source_gov)
        if source not in docs:
            if project_id and prefixes[project_id]+str(source) in docs: source=prefixes[project_id]+str(source)
            else: raise SourcePayloadError(f'Normalized object {table}/{oid} has no source document: {source}')
        kind=kind or table
        key=stable_pk(tenant_id,project_id,kind,oid)
        safe_data={k:v for k,v in data.items() if k not in ('_tombstone_source',)}
        deleted=data.get('_deleted_at',data.get('deleted_at'))
        if deleted and timestamp(deleted) is None: raise SourcePayloadError('Tombstone requires a full ISO deleted_at')
        row={'pk':key,'id':str(oid),'tenant_pk':stable_pk(tenant_id,None,'tenants',tenant_id),
             'project_pk':stable_pk(tenant_id,project_id,'projects',project_id) if project_id else None,
             'owner_pk':owner_pk(tenant_id,project_id,data),
             'created_at':timestamp(data.get('created_at',data.get('raised'))),
             'updated_at':timestamp(data.get('updated_at',data.get('updated'))),
             'deleted_at':timestamp(deleted),'revision':digest(safe_data),
             'source_version':str(data.get('version')) if data.get('version') is not None else None,
             'source_path':source,'source_pointer':str(pointer or data.get('source_pointer') or oid),
             'source_sha256':hashlib.sha256(docs[source].encode('utf-8')).hexdigest(),
             'source_commit_sha':data.get('source_commit_sha'),
             'source_actor_label':data.get('actor',data.get('owner')),
             'ingest_key':digest([epoch,tenant_id,project_id,kind,oid,digest(safe_data)]),
             'projection_epoch':epoch,'projection_state':'stale' if deleted else 'published',
             'projection_version':PROJECTION_VERSION,'source_data':safe_data,**extra}
        if key in rows[table] and canonical(rows[table][key])!=canonical(row):
            previous=rows[table][key]
            # One Git commit can be referenced by multiple change files. Its
            # objective data is identical; choose a deterministic provenance link.
            if table in ('git_commits','git_file_changes') and previous['source_data']==row['source_data']:
                if previous['source_path']<=row['source_path']:return key
            else:raise SourcePayloadError(f'Conflicting normalized rows for {table}/{oid}')
        rows[table][key]=row
        if register and table!='object_registry':
            reg={k:row[k] for k in ('pk','id','tenant_pk','project_pk','owner_pk','created_at','updated_at','deleted_at','revision','source_version',
                 'source_path','source_pointer','source_sha256','source_commit_sha','source_actor_label','ingest_key','projection_epoch','projection_state','projection_version','source_data')}
            reg['kind']=kind
            # Global tenant/principal rows have no project and are not discussion targets.
            if project_id: rows['object_registry'][key]=reg
        return key

    for tid,item in tenants.items():
        add('tenants',tid,None,tid,item,{'name':item['name'],'visibility_policy_ref':item.get('visibility_policy_ref'),
            'source_root_ref':item.get('source_root_ref')},item.get('source',source_gov),register=False)
    for (tid,pid),item in principals.items():
        if tid not in tenants: raise SourcePayloadError('Principal references unknown tenant')
        roles=item.get('roles',[])
        if isinstance(roles,str): roles=[roles]
        if not set(roles)<={'owner','maintainer','viewer'}: raise SourcePayloadError('Unsupported governance role')
        add('principals',tid,None,pid,item,{'display_name':item['display_name'],'actor_type':item.get('actor_type','human'),
            'identity_binding_ref':item.get('identity_binding_ref'),'roles':roles},item.get('source',source_gov),register=False)
    tombstones=payload['tombstones']
    if isinstance(tombstones,dict):
        tombstones=[dict(item,project_id=pid) for pid,items in tombstones.items() for item in items]
    source_tombstones=[]
    for tomb in tombstones:
        pid=tomb['project_id']; group=tomb['kind']
        if pid not in projects or group not in GROUP_TABLE:
            raise SourcePayloadError('Tombstone project/kind must reference a supported project object')
        item=copy.deepcopy(tomb['data'])
        if str(item.get('id'))!=str(tomb['id']): raise SourcePayloadError('Tombstone id must equal full data.id')
        item['_deleted_at']=tomb['deleted_at']
        item['_tombstone_source']=tomb.get('source',prefixes[pid]+'tombstones.yaml')
        if group in ('source_document','source_code'):
            source_tombstones.append((pid,group,item));continue
        destination='profileObjects' if group=='profile' else group
        if any(str(x['id'])==str(item['id']) for x in projects[pid].get(destination,[])):
            raise SourcePayloadError('Tombstone conflicts with a live object')
        projects[pid].setdefault(destination,[]).append(item)

    def links(tenant_id,pid,obj,from_kind,from_pk):
        source=obj.get('_tombstone_source') or obj.get('source') or prefixes[pid]+'project.yaml'
        for rid in obj.get('reqs',obj.get('x-requirements',[])):
            target=stable_pk(tenant_id,pid,'requirements',rid)
            identifier=f'{from_kind}:{obj["id"]}:requirement:{rid}'
            add('object_links',tenant_id,pid,identifier,dict(obj,id=identifier),{'from_pk':from_pk,'from_kind':from_kind,
                'relation':'requirement','to_pk':target,'to_kind':'requirements'},source,register=False)

    for pid,p in projects.items():
        if pid not in project_tenants or project_tenants[pid] not in tenants:
            raise SourcePayloadError('Every project must have explicit governance tenant mapping')
        tid=project_tenants[pid]
        base=prefixes[pid]
        # No injected collaboration snapshots or exports are accepted as source facts.
        if 'collaboration' in p: raise SourcePayloadError('Shared F/G project payload must not contain collaboration snapshots')
        meta={k:v for k,v in p.items() if k not in ('requirements','changes','records','tests','releases','incidents','audits','reviews',
             'screens','fields','apis','servers','errorCodes','contract','files','codeFiles','profileObjects','profile','stages','environments')}
        add('projects',tid,pid,pid,meta,{'name':p['name'],'description':p['description'],'type':p['type'],'kind':p['kind'],
            'example':p['example'],'stage':p['stage'],'focus_requirement_pk':stable_pk(tid,pid,'requirements',p['focus_requirement']),
            'onboarding':p.get('onboarding')},base+'project.yaml')
        repository_cache={}
        def repository(value,source,git=None,branch=None):
            rid=digest(str(value))[:32]
            if rid in repository_cache:return repository_cache[rid]
            row_data={'id':rid,'repo':value,'branch':branch,'source':source,'git_status':(git or {}).get('status')}
            available=(git or {}).get('status') in ('available','partial')
            key=add('repositories',tid,pid,rid,row_data,{'local_path':value if not str(value).startswith(('https://','http://')) else None,
                'remote_url':value if str(value).startswith(('https://','http://')) else None,'branch':branch,
                'availability':'reachable' if available else 'unavailable','unavailable_reason':None if available else (git or {}).get('reason','未提供可验证的仓库读取事实')},source)
            repository_cache[rid]=key
            return key
        # Change-declared repositories have authoritative extraction status.
        for change in p.get('changes',[]): repository(change.get('repo') or '',change.get('_tombstone_source') or change['source'],change.get('git'),p.get('branch'))
        repository(p.get('repo') or '',base+'project.yaml',next((c.get('git') for c in p.get('changes',[]) if c.get('repo')==p.get('repo')),None),p.get('branch'))
        for r in p['requirements']:
            key=add('requirements',tid,pid,r['id'],r,{'title':r['title'],'original':r['original'],'understanding':r['understanding'],
                'provenance':r.get('provenance'),'status':r['status'],'priority':r.get('priority'),'next_action':r.get('next'),'steps':r['steps']})
            for i,check in enumerate(r.get('checks',[])):
                ident=f'{r["id"]}:{i}'
                add('requirement_checks',tid,pid,ident,dict(r,id=ident,check=check),{'requirement_pk':key,'position':i,'text':check[0],'checked':check[1]},r.get('_tombstone_source') or r['source'],pointer=f'{r["id"]}/checks/{i}',register=False)
        for r in p.get('records',[]):
            key=add('activity_records',tid,pid,r['id'],r,{'title':r['title'],'stage':r['stage'],'environment_ref':r.get('env'),
                'actor_label':r.get('actor'),'detail':r.get('detail',''),'before_description':r.get('before'),'after_description':r.get('after'),
                'result':r.get('result'),'target_ref':r.get('target')})
            links(tid,pid,r,'activity_records',key)
        for test in p.get('tests',[]):
            key=add('test_cases',tid,pid,test['id'],test,{'title':test['title'],'requirement_pk':stable_pk(tid,pid,'requirements',test['req']),
                'environment_ref':test.get('env'),'expected':test.get('expected'),'actual':test.get('actual'),'result':test['result'],
                'record_pk':stable_pk(tid,pid,'activity_records',test['record']) if test.get('record') else None})
        for c in p.get('changes',[]):
            source=c.get('_tombstone_source') or c['source']
            rpk=repository(c.get('repo') or '',source,c.get('git'),p.get('branch'))
            cpk=add('changes',tid,pid,c['id'],c,{'title':c['title'],'narrative':c.get('body',''),'status':c['status'],
                'round':c.get('round'),'history_note':c.get('history_note'),'repository_pk':rpk})
            for rid in c['reqs']:
                ident=f'{c["id"]}:{rid}'
                add('change_requirements',tid,pid,ident,dict(c,id=ident),{'change_pk':cpk,'requirement_pk':stable_pk(tid,pid,'requirements',rid)},source,register=False)
            links(tid,pid,c,'changes',cpk)
            extracted={git['sha']:git for git in c.get('git',{}).get('commits',[])}
            git_keys={}
            for sha,g in extracted.items():
                gid=f'{rpk}:{sha}'
                total=g.get('totals',{})
                gkey=add('git_commits',tid,pid,gid,g,{'repository_pk':rpk,'sha':sha,'parent_shas':g.get('parents',[]),
                    'author_label':g.get('author'),'authored_at':timestamp(g.get('date')),'committed_at':timestamp(g.get('committed_at')),
                    'subject':g.get('subject',''),'file_count':len(g.get('files',[])),'insertions':total.get('additions'),'deletions':total.get('deletions')},source,kind='git_commits',register=False)
                git_keys[sha]=gkey
                for n,f in enumerate(g.get('files',[])):
                    fileid=f'{gid}:{n}:{f.get("path","")}'
                    add('git_file_changes',tid,pid,fileid,f,{'git_commit_pk':gkey,'old_path':f.get('old_path'),'new_path':f.get('path'),
                        'change_kind':f.get('status','modified'),'added_lines':f.get('additions'),'deleted_lines':f.get('deletions'),
                        'patch':f.get('patch',''),'hunks':f.get('hunks',[]),'before_blob_sha':f.get('before_blob'),
                        'after_blob_sha':f.get('after_blob'),'extraction_status':'partial' if f.get('truncated') else 'available' if f.get('patch_available',True) else 'unavailable'},source,register=False)
            declared=c.get('commit',[])
            if isinstance(declared,str):declared=[declared]
            for sha in dict.fromkeys(declared):
                resolved=next((full for full in extracted if full==sha or full.startswith(sha)),None)
                ident=f'{c["id"]}:{sha}'
                add('change_commits',tid,pid,ident,{'id':ident,'sha':sha,'change':c['id'],'git':c.get('git',{}),'source':source},
                    {'change_pk':cpk,'repository_pk':rpk,'declared_commit_sha':sha,'git_commit_pk':git_keys.get(resolved),
                     'resolution_status':'resolved' if resolved else 'unavailable','resolution_reason':None if resolved else c.get('git',{}).get('reason','无法提取')},source,register=False)
        for group,table in [('releases','releases'),('incidents','incidents'),('audits','security_audits'),('reviews','retrospectives')]:
            for obj in p.get(group,[]):
                extra={'title':obj['title'],'status':obj['status']}
                if group=='releases':extra.update(version_label=obj.get('version'),environment_ref=obj.get('env'),change_ids=obj.get('changes',[]),test_ids=obj.get('tests',[]),receipt_ref=obj.get('receipt_ref'),rollback_notes=obj.get('rollback_notes'))
                if group=='incidents':extra.update(severity=obj.get('severity'),symptom=obj.get('symptom'),expected=obj.get('expected'),evidence_refs=obj.get('evidence_refs',[]),cause=obj.get('cause'),resolution=obj.get('resolution'))
                if group=='audits':extra.update(scope=obj.get('scope'),findings=obj.get('findings',[]),auditor_label=obj.get('auditor_label'),evidence_refs=obj.get('evidence_refs',[]))
                if group=='reviews':extra.update(observations=obj.get('observations'),interpretations=obj.get('interpretations'),decisions=obj.get('decisions'),followup_requirement_ids=obj.get('followup_requirement_ids',[]))
                key=add(table,tid,pid,obj['id'],obj,extra);links(tid,pid,obj,table,key)
        contract=p.get('contract')
        if p['type']=='software':
            if not isinstance(contract,dict):raise SourcePayloadError('Shared loader must provide p.contract for software projects')
            cpk=add('api_contracts',tid,pid,'contract',contract,{'openapi_version':contract['openapi'],'title':contract['info']['title'],
                'contract_version':contract['info']['version'],'document':contract,'validation_profile':'repository offline OpenAPI 3.1 schema profile'},base+'api/openapi.json')
            for index,server in enumerate(contract.get('servers',[])):
                add('environments',tid,pid,server['x-environment'],server,{'contract_pk':cpk,'server_ref':server['x-environment'],
                    'label':server.get('description'),'base_url':server['url'],'deployment_state':server.get('x-deployment-state')},base+'api/openapi.json',pointer=f'/servers/{index}')
        object_groups=[('screens','screen'),('fields','field'),('apis','api_operation'),('profileObjects',None)]
        for group,subtype in object_groups:
            for obj in p.get(group,[]):
                objkind=subtype or obj.get('group','profile')
                kind='master:'+objkind
                key=add('master_objects',tid,pid,obj['id'],obj,{'project_type':p['type'],'object_type':objkind,
                    'title':obj.get('title',obj.get('name',obj['id'])),'status':obj.get('status'),'payload':obj},kind=kind)
                links(tid,pid,obj,kind,key)
        if p['type']=='software':
            prototype=p.get('prototype',{'kind':'none','tasks':[]})
            add('master_objects',tid,pid,'prototype',prototype,{'project_type':p['type'],'object_type':'prototype',
                'title':'页面毛坯初始数据','status':None,'payload':prototype},base+'ui/prototype.yaml',kind='master:prototype')
        for path,text in docs.items():
            if path.startswith(base):
                obj={'id':path[len(base):],'path':path,'content':text}
                add('master_objects',tid,pid,obj['id'],obj,{'project_type':p['type'],'object_type':'source_document',
                    'title':obj['id'],'status':None,'payload':obj},path,kind='master:source_document')
        for entry in p.get('codeFiles',[]):
            # These are already authorized/read by the shared loader. Their keys
            # are workspace-relative, unlike project documents; never re-open them.
            add('master_objects',tid,pid,entry['id'],entry,{'project_type':p['type'],'object_type':'source_code',
                'title':entry.get('title',entry['id']),'status':None,'payload':entry},entry['path'],kind='master:source_code')
        for tomb_pid,subtype,obj in source_tombstones:
            if tomb_pid==pid:
                add('master_objects',tid,pid,obj['id'],obj,{'project_type':p['type'],'object_type':subtype,
                    'title':obj.get('title',obj['id']),'status':'已删除','payload':obj},obj['_tombstone_source'],kind='master:'+subtype)
    # Do not hide normalized payload/reference mistakes behind deferred FK failures.
    registry=rows['object_registry']
    for link in rows['object_links'].values():
        if link['from_pk'] not in registry or link['to_pk'] not in registry:
            raise SourcePayloadError('Normalized object link points to an absent source object')
    return {table:[items[key] for key in sorted(items,key=str)] for table,items in rows.items()}
