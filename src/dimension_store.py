from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
import psycopg2.extensions
import psycopg2.extras
from src.reconstruction import DimRecord
logger = logging.getLogger(__name__)

def fetch_current_dim_record(conn: psycopg2.extensions.connection, customer_id: str) -> Optional[dict]:
    sql = '\n        SELECT customer_sk, customer_id, customer_name, city,\n               effective_start, effective_end, is_current, record_hash, run_id\n        FROM   dim_customer\n        WHERE  customer_id = %(customer_id)s\n          AND  is_current = TRUE\n    '
    with conn.cursor() as cur:
        cur.execute(sql, {'customer_id': customer_id})
        row = cur.fetchone()
    return dict(row) if row else None

def fetch_customer_dim_history(conn: psycopg2.extensions.connection, customer_id: str) -> list[dict]:
    sql = '\n        SELECT customer_sk, customer_id, customer_name, city,\n               effective_start, effective_end, is_current, record_hash, run_id\n        FROM   dim_customer\n        WHERE  customer_id = %(customer_id)s\n        ORDER  BY effective_start ASC\n    '
    with conn.cursor() as cur:
        cur.execute(sql, {'customer_id': customer_id})
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def delete_customer_dim_records(conn: psycopg2.extensions.connection, customer_id: str) -> int:
    sql = '\n        DELETE FROM dim_customer\n        WHERE  customer_id = %(customer_id)s\n    '
    with conn.cursor() as cur:
        cur.execute(sql, {'customer_id': customer_id})
        deleted = cur.rowcount
    logger.debug('Deleted %d dim_customer rows for customer_id=%s', deleted, customer_id)
    return deleted

def insert_dim_records(conn: psycopg2.extensions.connection, records: list[DimRecord]) -> int:
    if not records:
        return 0
    sql = '\n        INSERT INTO dim_customer (\n            customer_id,\n            customer_name,\n            city,\n            effective_start,\n            effective_end,\n            is_current,\n            record_hash,\n            created_at,\n            run_id\n        ) VALUES (\n            %(customer_id)s,\n            %(customer_name)s,\n            %(city)s,\n            %(effective_start)s,\n            %(effective_end)s,\n            %(is_current)s,\n            %(record_hash)s,\n            NOW(),\n            %(run_id)s\n        )\n    '
    params = [{'customer_id': r.customer_id, 'customer_name': r.customer_name, 'city': r.city, 'effective_start': r.effective_start, 'effective_end': r.effective_end, 'is_current': r.is_current, 'record_hash': r.record_hash, 'run_id': r.run_id} for r in records]
    with conn.cursor() as cur:
        cur.executemany(sql, params)
    inserted = len(records)
    logger.info('Inserted %d dim_customer records for customer_id=%s', inserted, records[0].customer_id)
    return inserted

def replace_customer_history(conn: psycopg2.extensions.connection, customer_id: str, records: list[DimRecord]) -> tuple[int, int]:
    deleted = delete_customer_dim_records(conn, customer_id)
    inserted = insert_dim_records(conn, records)
    return (deleted, inserted)
