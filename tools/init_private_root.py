"""Create an empty external private root; never import an actual project."""
import argparse,json
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]

def initialize(destination):
    destination=Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(ROOT):raise ValueError('Choose a new external directory; no overwrite/import')
    destination.mkdir(parents=True)
    # Empty mappings are valid until the user explicitly selects a project.
    governance={'tenants':[{'id':'private-local','name':'私有工作区'}],
        'principals':[{'id':'private-owner','tenant_id':'private-local','display_name':'私有项目维护者','actor_type':'human','roles':['owner']}],
        'project_tenants':{},'project_owners':{}}
    (destination/'governance.yaml').write_text(yaml.safe_dump(governance,allow_unicode=True,sort_keys=False),encoding='utf-8')
    (destination/'README.md').write_text('空的私有资料根，尚未接入任何项目。用户指定项目后创建对应目录，并在governance.yaml的project_tenants/project_owners添加归属。账号登录映射另行配置到本机.local/accounts.json，不在这里保存口令。\n',encoding='utf-8')
    return {'ok':True,'projects_imported':0}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path);args=parser.parse_args()
    print(json.dumps(initialize(args.destination)))
