"""Seed or edit the four source tables in integration tests."""
from contextlib import contextmanager
import sqlite3

import record_sources


@contextmanager
def named_rows(db):
    previous=db.row_factory
    db.row_factory=sqlite3.Row
    try:
        yield
    finally:
        db.row_factory=previous


def seed(db, table, fields, values):
    columns=dict(zip(fields,values,strict=True))
    owner=columns.pop('id')
    body=record_sources.object_value(columns.pop('body'),mutable=False)
    with named_rows(db):
        record_sources.write(db,table,owner,body,columns=columns,insert=True)


def seed_many(db, table, fields, rows):
    for values in rows:
        seed(db,table,fields,values)


def replace(db, table, owner, value, *, columns=None, bump=False):
    with named_rows(db):
        record_sources.write(db,table,owner,record_sources.object_value(value,mutable=False),columns=columns,bump=bump)


def patch_values(db, table, owner, updates=(), *, remove=()):
    with named_rows(db):
        owners=[owner] if owner is not None else [r[0] for r in db.execute('SELECT id FROM '+table)]
        for rid in owners:
            body=record_sources.read(db,table,rid)
            def parent(path):
                item=body
                for part in path[:-1]:
                    item=item[part]
                return item
            for path,value in updates:
                parent(path)[path[-1]]=value
            for path in remove:
                parent(path).pop(path[-1],None)
            record_sources.write(db,table,rid,body,bump=False)
