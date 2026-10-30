from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING
import psycopg2.extensions
import psycopg2.extras
from src.validation import AcceptedEvent, RejectedEvent
if TYPE_CHECKING:
    pass
logger = logging.getLogger(__name__)

def fetch_ledger_entries(conn: psycopg2.extensions.connection, event_ids: list[str]) -> dict[str, str]:
    if not event_ids:
        return {}
    sql = '\n        SELECT event_id, payload_hash\n        FROM   customer_events\n        WHERE  event_id = ANY(%(ids)s)\n    '
    with conn.cursor() as cur:
        cur.execute(sql, {'ids': event_ids})
        rows = cur.fetchall()
    result = {row['event_id']: row['payload_hash'] for row in rows}
    logger.debug('Ledger lookup: queried=%d found=%d', len(event_ids), len(result))
    return result

def insert_events(conn: psycopg2.extensions.connection, events: list[AcceptedEvent], run_id: str) -> int:
    if not events:
        return 0
    sql = '\n        INSERT INTO customer_events (\n            event_id,\n            customer_id,\n            customer_name,\n            city,\n            event_timestamp,\n            source_file,\n            source_row_number,\n            ingested_at,\n            payload_hash,\n            source_sequence,\n            run_id\n        ) VALUES (\n            %(event_id)s,\n            %(customer_id)s,\n            %(customer_name)s,\n            %(city)s,\n            %(event_timestamp)s,\n            %(source_file)s,\n            %(source_row_number)s,\n            NOW(),\n            %(payload_hash)s,\n            %(source_sequence)s,\n            %(run_id)s\n        )\n    '
    params = [{'event_id': e.event_id, 'customer_id': e.customer_id, 'customer_name': e.customer_name, 'city': e.city, 'event_timestamp': e.event_timestamp, 'source_file': e.source_file, 'source_row_number': e.source_row_number, 'payload_hash': e.payload_hash, 'source_sequence': e.source_sequence, 'run_id': run_id} for e in events]
    with conn.cursor() as cur:
        cur.executemany(sql, params)
    inserted = len(events)
    logger.info('Inserted %d new events into customer_events', inserted)
    return inserted

def insert_rejected_records(conn: psycopg2.extensions.connection, records: list[RejectedEvent], run_id: str, source_file: str='') -> int:
    if not records:
        return 0
    sql = '\n        INSERT INTO rejected_records (\n            run_id,\n            source_file,\n            source_row_number,\n            raw_payload,\n            rejection_reason,\n            rejected_at\n        ) VALUES (\n            %(run_id)s,\n            %(source_file)s,\n            %(source_row_number)s,\n            %(raw_payload)s,\n            %(rejection_reason)s,\n            NOW()\n        )\n    '
    params = [{'run_id': run_id, 'source_file': r.source_file or source_file, 'source_row_number': r.source_row_number, 'raw_payload': psycopg2.extras.Json(r.raw_payload) if isinstance(r.raw_payload, dict) else psycopg2.extras.Json({'raw': r.raw_payload}), 'rejection_reason': r.rejection_reason} for r in records]
    with conn.cursor() as cur:
        cur.executemany(sql, params)
    inserted = len(records)
    logger.info('Inserted %d rejected records', inserted)
    return inserted
