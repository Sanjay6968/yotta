from __future__ import annotations
import logging
import uuid
import psycopg2.extensions
import psycopg2.extras
logger = logging.getLogger(__name__)

def generate_run_id() -> str:
    return str(uuid.uuid4())

def create_run(conn: psycopg2.extensions.connection, run_id: str, input_file: str) -> None:
    sql = "\n        INSERT INTO pipeline_runs (\n            run_id, started_at, status, input_file\n        ) VALUES (\n            %(run_id)s, NOW(), 'running', %(input_file)s\n        )\n    "
    with conn.cursor() as cur:
        cur.execute(sql, {'run_id': run_id, 'input_file': input_file})
    logger.info('Created pipeline run: run_id=%s', run_id)

def complete_run(conn: psycopg2.extensions.connection, run_id: str, *, status: str, input_count: int=0, accepted_count: int=0, rejected_count: int=0, duplicate_count: int=0, conflict_count: int=0, event_insert_count: int=0, dimension_insert_count: int=0, dimension_update_count: int=0, late_event_count: int=0, processing_duration_ms: int=0, error_message: str | None=None) -> None:
    sql = '\n        UPDATE pipeline_runs SET\n            finished_at             = NOW(),\n            status                  = %(status)s,\n            input_count             = %(input_count)s,\n            accepted_count          = %(accepted_count)s,\n            rejected_count          = %(rejected_count)s,\n            duplicate_count         = %(duplicate_count)s,\n            conflict_count          = %(conflict_count)s,\n            event_insert_count      = %(event_insert_count)s,\n            dimension_insert_count  = %(dimension_insert_count)s,\n            dimension_update_count  = %(dimension_update_count)s,\n            late_event_count        = %(late_event_count)s,\n            processing_duration_ms  = %(processing_duration_ms)s,\n            error_message           = %(error_message)s\n        WHERE run_id = %(run_id)s\n    '
    with conn.cursor() as cur:
        cur.execute(sql, {'run_id': run_id, 'status': status, 'input_count': input_count, 'accepted_count': accepted_count, 'rejected_count': rejected_count, 'duplicate_count': duplicate_count, 'conflict_count': conflict_count, 'event_insert_count': event_insert_count, 'dimension_insert_count': dimension_insert_count, 'dimension_update_count': dimension_update_count, 'late_event_count': late_event_count, 'processing_duration_ms': processing_duration_ms, 'error_message': error_message})
    logger.info('Completed pipeline run: run_id=%s status=%s', run_id, status)
