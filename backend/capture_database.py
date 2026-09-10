"""Read-only recovery receipts adapted from the independent round-4 reviewer.

The reviewer's PostgreSQL to_jsonb row-hash algorithm is retained. Receipts store
all-column row hashes, column names and constraints; never raw collaboration rows.
Only the isolated devplm_rebuild_<suffix> database namespace is accepted.
"""
import hashlib
import json
import re

from .db import D_TABLES, E_TABLES
from .projection import F_TABLES

TABLES = (*F_TABLES, *D_TABLES, *E_TABLES)


def capture(conn, source_fingerprint):
    from psycopg import sql
    if not re.fullmatch(r'[0-9a-f]{64}', source_fingerprint):
        raise ValueError('A real source fingerprint is required')
    result = {'format': 1, 'source_fingerprint': source_fingerprint, 'tables': {}}
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout = '30s'")
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        info = conn.execute('SELECT current_database() AS name, oid, clock_timestamp()::text AS time FROM pg_database WHERE datname=current_database()').fetchone()
        if not re.fullmatch(r'devplm_rebuild_[a-z0-9_]+', info['name']):
            raise ValueError('Capture refuses a database outside the disposable namespace')
        result.update(database=info['name'], database_oid=info['oid'], captured_at=info['time'])
        present = {row['relname'] for row in conn.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='devplm' AND c.relkind IN ('r','p')").fetchall()}
        result['extra_tables'] = sorted(present - set(TABLES))
        for name in TABLES:
            if name not in present:
                result['tables'][name] = {'exists': False}
                continue
            columns = [row['column_name'] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='devplm' AND table_name=%s ORDER BY ordinal_position", (name,)).fetchall()]
            constraints = [dict(type=row['contype'], validated=row['convalidated'], deferrable=row['condeferrable'],
                initially_deferred=row['condeferred'], definition=row['definition']) for row in conn.execute("SELECT contype,convalidated,condeferrable,condeferred,pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='devplm' AND t.relname=%s ORDER BY contype,pg_get_constraintdef(c.oid)", (name,)).fetchall()]
            query = sql.SQL('SELECT pk::text AS pk,to_jsonb(t)::text AS body FROM {} t ORDER BY pk').format(sql.Identifier('devplm', name))
            rows = {row['pk']: hashlib.sha256(row['body'].encode('utf-8')).hexdigest() for row in conn.execute(query).fetchall()}
            table_hash = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            result['tables'][name] = {'exists': True, 'columns': columns, 'constraints': constraints,
                'count': len(rows), 'sha256': table_hash, 'rows': rows}
    return result


def assert_projection_equal(left, right):
    """Same assertions as the reviewer's independent five-receipt comparison."""
    if left['source_fingerprint'] != right['source_fingerprint']:
        raise AssertionError('Projection input fingerprint changed')
    for name in F_TABLES:
        before, after = left['tables'][name], right['tables'][name]
        if any(before[key] != after[key] for key in ('columns', 'count', 'rows', 'sha256')):
            raise AssertionError('All-column projection recovery mismatch: ' + name)


def assert_schema(receipt, empty=False):
    if len(TABLES) != 31 or len(set(TABLES)) != 31:
        raise AssertionError('Expected 31 reviewed model tables')
    for name in TABLES:
        table = receipt['tables'].get(name, {})
        if not table.get('exists') or 'pk' not in table['columns']:
            raise AssertionError('Missing model table or PK: ' + name)
        if not any(c['type'] == 'p' for c in table['constraints']):
            raise AssertionError('Missing database primary key: ' + name)
        if not all(c['validated'] for c in table['constraints'] if c['type'] in ('f', 'c')):
            raise AssertionError('Unvalidated constraint: ' + name)
        if empty and table['count'] != 0:
            raise AssertionError('Fresh model table is not empty: ' + name)
