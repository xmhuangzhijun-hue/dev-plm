"""Nonsecret settings plus registered local secret references.

No DSN or token is logged. .env contains references and locations, never values.
The offline builder never imports this module or requires a database driver.
"""
from pathlib import Path
import os
import re

ROOT = Path(__file__).resolve().parents[1]
SECRET_ROOT = Path(os.environ.get('LOCALAPPDATA', '')) / 'XiaomoSecrets'


class ConfigurationError(RuntimeError):
    pass


def settings():
    from dotenv import dotenv_values
    file = Path(os.environ.get('DEVPLM_ENV_FILE', ROOT / '.env'))
    return {**dotenv_values(file), **os.environ}


def secret(reference):
    """Resolve one SEC id; never return registry/secret contents in an error."""
    import yaml
    if not isinstance(reference, str) or not re.fullmatch(r'SEC-\d{4}-\d{3,}', reference):
        raise ConfigurationError('需要有效的本机凭据登记 ID。')
    try:
        registry = yaml.safe_load((SECRET_ROOT / 'registry.yaml').read_text(encoding='utf-8'))
        entries = registry if isinstance(registry, list) else registry.get('secrets', registry.get('entries', []))
        if isinstance(entries, dict):
            entries = list(entries.values())
        found = [e for e in entries if isinstance(e, dict) and e.get('id') == reference and e.get('status') == 'active']
        if len(found) != 1 or not found[0]['secret_location'].startswith('file:'):
            raise ValueError()
        path = (SECRET_ROOT / found[0]['secret_location'][5:]).resolve()
        if not path.is_relative_to((SECRET_ROOT / 'private').resolve()):
            raise ValueError()
        value = path.read_text(encoding='utf-8').strip()
        if not value:
            raise ValueError()
        return value
    except Exception:
        raise ConfigurationError('登记凭据不可用；检查本机登记状态及文件权限。') from None


def get_database_url(role='api'):
    from psycopg.conninfo import make_conninfo
    if role not in ('admin', 'api', 'sync'):
        raise ValueError('Unknown role')
    env = settings()
    reference = env.get('DEVPLM_DB_' + role.upper() + '_SECRET')
    host = env.get('DEVPLM_DB_HOST', '127.0.0.1')
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise ConfigurationError('本轮数据库仅允许本机连接。')
    return make_conninfo(host=host, port=env.get('DEVPLM_DB_PORT', '55432'),
        dbname=env.get('DEVPLM_DB_NAME', 'devplm'),
        user=env.get('DEVPLM_DB_' + role.upper() + '_USER', {'admin':'postgres','api':'devplm_api_login','sync':'devplm_sync_login'}[role]),
        password=secret(reference), connect_timeout=5)


def account_bindings():
    """Nonsecret identifier -> tenant/principal/credential-reference mapping."""
    import json
    file = Path(settings().get('DEVPLM_ACCOUNTS_FILE', ROOT / '.local/accounts.json'))
    try:
        value = json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(value, list):
            raise ValueError()
        return value
    except Exception:
        raise ConfigurationError('本机登录主体映射未配置。') from None
