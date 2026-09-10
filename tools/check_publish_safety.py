"""Fail-closed inspection of actual publish bytes; never rewrites input.

Private identities/roots can be supplied in an external JSON inventory. Unknown
identity fields are rejected; arbitrary names in prose still require human review.
Credential-looking excerpts are masked so diagnostic output cannot leak a secret.
"""
import argparse
import html
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.html','.css','.js','.json','.md','.txt','.yaml','.yml','.py','.cjs','.sql','.svg','.toml','.ps1','.example','.gitattributes','.gitignore',''}
PATTERNS = {
    'absolute_path': re.compile(r'(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/][^\s"<>|]*|\\\\[A-Za-z0-9_.-]+[\\/][^\s"<>|]*|/(?:home|Users|root|mnt|media|Volumes|private|tmp|var|opt|srv|workspace|workspaces)/[^\s"<>|]*)'),
    'email': re.compile(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
    'credential_reference': re.compile(r'\bSEC-\d{4}-\d+\b'),
    'credential_shape': re.compile(r'(?i)(?:\b(?:password|api[_-]?key|access[_-]?token|token|secret)\b["\x27]?\s*[:=]\s*["\x27]?[A-Za-z0-9_./+=-]{20,}|\bBearer\s+[A-Za-z0-9_./+=-]{20,}|\b(?:ghp_|github_pat_|sk_live_|sk-proj-)[A-Za-z0-9_-]{20,}|\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'),
}
IDENTITY = re.compile(r'(?:^|[\s,{])["\x27]?(?:author|username|user_name|real_name|full_name|owner)["\x27]?\s*:\s*["\x27]([^"\x27\n]+)["\x27]')


def normalized(line):
    value = line
    for _ in range(4):
        changed = html.unescape(unquote(value))
        changed = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1],16)), changed)
        changed = changed.replace('\\"','"').replace('\\/','/').replace('\\\\','\\')
        if changed == value: break
        value = changed
    return value


def read_policy(path):
    policy=json.loads(Path(path).read_text(encoding='utf-8'))
    if policy.get('version')!=1 or not isinstance(policy.get('projects'),list):
        raise ValueError('Invalid publication policy')
    for key in ('identity_values','allowlist'):
        for item in policy.get(key,[]):
            allowed={'value','reason'} if key=='identity_values' else {'value','reason','kind','file'}
            if set(item)!=allowed or not all(isinstance(v,str) and v.strip() for v in item.values()):
                raise ValueError('Allowlist entries require exact value, scope, and reason; regex rules are forbidden')
            if key=='allowlist' and (item['file']=='*' or item['kind'] not in {*PATTERNS,'identity','private_value'}):
                raise ValueError('Allowlist must use an exact file and known category')
    for item in policy.get('binary_files',[]):
        if set(item)!={'file','sha256','reason'} or not item['reason'].strip() or not re.fullmatch('[a-f0-9]{64}',item['sha256']) or '*' in item['file']:
            raise ValueError('Binary inventory requires an exact file, checksum and review reason')
    return policy


def inspect_tree(directory, policy=None, private_values=(), require_manifest=True):
    if Path(directory).is_symlink():return [{'file':'.','line':1,'kind':'symlink','excerpt':'Publish root must not be a symlink'}],0
    directory=Path(directory).resolve()
    policy=policy or read_policy(ROOT/'publication-policy.json')
    issues=[];count=0
    allowed_identities={i['value'] for i in policy.get('identity_values',[])}
    def report(file,line,kind,value):
        if any(a['file']==file and a['kind']==kind and a['value']==value for a in policy.get('allowlist',[])):return
        excerpt='[credential-like value withheld]' if kind=='credential_shape' else value[:140]
        issues.append({'file':file,'line':line,'kind':kind,'excerpt':excerpt})
    if not directory.is_dir():return [{'file':'.','line':1,'kind':'missing_directory','excerpt':'No publish directory'}],0
    for path in sorted(directory.rglob('*')):
        label=path.relative_to(directory).as_posix()
        if path.is_symlink():
            report(label,1,'symlink','Symlinks are not publishable');continue
        if not path.is_file():continue
        count+=1
        binary=next((b for b in policy.get('binary_files',[]) if b['file']==label),None)
        if binary:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=binary['sha256']:report(label,1,'binary_changed','Reviewed binary checksum changed')
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            report(label,1,'uninspected_binary','Unsupported binary format; add a reviewed byte-level inspector first');continue
        try:text=path.read_bytes().decode('utf-8-sig')
        except (UnicodeError,OSError):
            report(label,1,'unreadable_content','Content could not be inspected as UTF-8');continue
        for line_no,raw in enumerate([label,*text.splitlines()],0):
            line=normalized(raw)
            for kind,pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    value=match.group()
                    if kind=='email' and value.lower().endswith('.invalid'):continue
                    report(label,max(1,line_no),kind,value)
            for match in IDENTITY.finditer(line):
                if match[1] not in allowed_identities:report(label,max(1,line_no),'identity',match[1])
            if path.suffix.lower() in {'.yaml','.yml','.md'}:
                match=re.match(r'^\s*(?:author|username|user_name|real_name|full_name|owner):\s*([^\s"\x27].*?)\s*$',line)
                if match and match[1] not in allowed_identities:report(label,max(1,line_no),'identity',match[1])
            for value in private_values:
                if value and str(value).casefold() in line.casefold():report(label,max(1,line_no),'private_value',str(value))
    if require_manifest:
        try:
            manifest=json.loads((directory/'publication.json').read_text(encoding='utf-8'))
            content=(directory/'assets/project-data.js').read_text(encoding='utf-8')
            data=json.loads(content.split('window.DEVPLM_DATA = ',1)[1].strip().removesuffix(';'))
            ids=[p['id'] for p in data['projects']]
            if manifest.get('mode')!='public' or manifest.get('project_ids')!=ids or len(ids)!=len(set(ids)) or set(ids)-set(policy['projects']):raise ValueError()
            if any(p['id']!='dev-plm' and not p['example'] for p in data['projects']):raise ValueError()
            if any(p.get('collaboration') for p in data['projects']):raise ValueError()
        except (ValueError,KeyError,IndexError,OSError):
            report('publication.json',1,'publication_scope','Missing or inconsistent public-build manifest / approved project set')
    return issues,count


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--policy',type=Path,default=ROOT/'publication-policy.json')
    parser.add_argument('--private-inventory',type=Path,help='External JSON containing identities, roots and project_ids; never copied to output')
    parser.add_argument('--private-data-root',type=Path,action='append',default=[])
    parser.add_argument('--source-tree',action='store_true',help='Inspect a clean source export (no site manifest required)')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    try:
        values=[]
        if args.private_inventory:
            inventory=json.loads(args.private_inventory.read_text(encoding='utf-8'))
            if not isinstance(inventory,dict) or set(inventory)-{'identities','roots','project_ids'}:raise ValueError('Invalid private inventory')
            for key in ('identities','roots','project_ids'):
                entries=inventory.get(key,[])
                if not isinstance(entries,list) or any(not isinstance(v,str) or not v.strip() for v in entries):raise ValueError('Invalid private inventory entries')
                values.extend(entries)
        for root in args.private_data_root:
            if not root.is_dir():raise ValueError('Private inventory root is unavailable')
            values.extend([str(root.resolve()),root.resolve().as_posix()])
            for file in root.glob('*/project.yaml'):
                import yaml
                values.append(yaml.safe_load(file.read_text(encoding='utf-8'))['id'])
        issues,count=inspect_tree(args.directory,read_policy(args.policy),values,not args.source_tree)
        result={'ok':not issues,'files_inspected':count,'findings':issues}
    except Exception:
        result={'ok':False,'files_inspected':0,'findings':[{'file':'.','line':1,'kind':'inspection_failed','excerpt':'Invalid/unavailable policy, inventory or input; no publish approval'}]}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
