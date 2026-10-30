from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
import psycopg2.extensions
import psycopg2.extras
from src.deduplication import classify_events
from src.dimension_store import fetch_customer_dim_history, replace_customer_history
from src.event_store import fetch_ledger_entries, insert_events, insert_rejected_records
from src.ingestion import ingest_file
from src.pipeline_store import complete_run, create_run, generate_run_id
from src.reconstruction import reconstruct_customer_history
from src.storage import get_connection, transaction
from src.config import get_config
logger = logging.getLogger(__name__)

@dataclass
class PipelineResult:
    run_id: str
    status: str
    input_file: str
    input_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    conflict_count: int = 0
    event_insert_count: int = 0
    dimension_insert_count: int = 0
    dimension_update_count: int = 0
    late_event_count: int = 0
    processing_duration_ms: int = 0
    error_message: str | None = None
    customers_affected: list[str] = field(default_factory=list)

def run_pipeline(input_file: str) -> PipelineResult:
    cfg = get_config()
    run_id = generate_run_id()
    start_ms = time.monotonic_ns() // 1000000
    result = PipelineResult(run_id=run_id, status='running', input_file=str(input_file))
    logger.info('=' * 60)
    logger.info('ChronoLedger pipeline starting')
    logger.info('  run_id     : %s', run_id)
    logger.info('  input_file : %s', input_file)
    logger.info('=' * 60)
    conn = get_connection(cfg)
    conn.autocommit = False
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    conn.autocommit = True
    _exec(conn, "\n        INSERT INTO pipeline_runs (run_id, input_file, started_at, status)\n        VALUES (%s, %s, NOW(), 'running')\n    ", (run_id, str(input_file)))
    conn.autocommit = False
    try:
        logger.info('Step 1: Ingesting %s', input_file)
        ingestion = ingest_file(input_file)
        if ingestion.schema_error:
            raise ValueError(f'Schema error: {ingestion.schema_error}')
        result.input_count = ingestion.input_count
        result.accepted_count = ingestion.accepted_count
        result.rejected_count = ingestion.rejected_count
        logger.info('  Ingested: total=%d accepted=%d rejected=%d', result.input_count, result.accepted_count, result.rejected_count)
        with transaction(conn):
            if ingestion.rejected:
                logger.info('Step 2: Writing %d rejected records', len(ingestion.rejected))
                insert_rejected_records(conn, ingestion.rejected, run_id=run_id, source_file=str(input_file))
            logger.info('Step 3: Deduplication')
            incoming_ids = [e.event_id for e in ingestion.accepted]
            ledger = fetch_ledger_entries(conn, incoming_ids)
            dedup = classify_events(ingestion.accepted, ledger=ledger, source_file=str(input_file), run_id=run_id)
            result.duplicate_count = dedup.duplicate_count
            result.conflict_count = dedup.conflict_count
            logger.info('  Dedup: new=%d duplicates=%d conflicts=%d', dedup.new_count, dedup.duplicate_count, dedup.conflict_count)
            if dedup.conflicts:
                insert_rejected_records(conn, dedup.conflicts, run_id=run_id, source_file=str(input_file))
            if dedup.new_events:
                logger.info('Step 5: Inserting %d new events into ledger', dedup.new_count)
                result.event_insert_count = insert_events(conn, dedup.new_events, run_id=run_id)
            affected_customers = sorted({e.customer_id for e in dedup.new_events})
            result.customers_affected = affected_customers
            logger.info('Step 6: Rebuilding dimension for %d affected customers', len(affected_customers))
            dim_inserts = 0
            dim_updates = 0
            late_count = 0
            for customer_id in affected_customers:
                all_events_for_customer = _fetch_all_customer_events(conn, customer_id)
                old_history = fetch_customer_dim_history(conn, customer_id)
                if old_history:
                    current_start = old_history[-1]['effective_start']
                    new_for_customer = [e for e in dedup.new_events if e.customer_id == customer_id]
                    for e in new_for_customer:
                        if e.event_timestamp < current_start:
                            late_count += 1
                            logger.info('  Late event: event_id=%s ts=%s before current_start=%s', e.event_id, e.event_timestamp, current_start)
                new_records = reconstruct_customer_history(all_events_for_customer, run_id=run_id)
                deleted, inserted = replace_customer_history(conn, customer_id, new_records)
                dim_inserts += inserted
                if deleted > 0:
                    dim_updates += 1
                logger.info('  Customer %s: deleted=%d inserted=%d versions', customer_id, deleted, inserted)
            result.dimension_insert_count = dim_inserts
            result.dimension_update_count = dim_updates
            result.late_event_count = late_count
        result.status = 'success'
        result.processing_duration_ms = time.monotonic_ns() // 1000000 - start_ms
        logger.info('=' * 60)
        logger.info('Pipeline complete: run_id=%s status=success duration=%dms', run_id, result.processing_duration_ms)
        logger.info('  events inserted    : %d', result.event_insert_count)
        logger.info('  dim versions       : %d', result.dimension_insert_count)
        logger.info('  duplicates skipped : %d', result.duplicate_count)
        logger.info('  conflicts/rejects  : %d', result.rejected_count + result.conflict_count)
        logger.info('  late events        : %d', result.late_event_count)
        logger.info('=' * 60)
    except Exception as exc:
        result.status = 'failed'
        result.error_message = str(exc)
        result.processing_duration_ms = time.monotonic_ns() // 1000000 - start_ms
        logger.exception('Pipeline failed: %s', exc)
    finally:
        conn.autocommit = True
        complete_run(conn, run_id, status=result.status, input_count=result.input_count, accepted_count=result.accepted_count, rejected_count=result.rejected_count, duplicate_count=result.duplicate_count, conflict_count=result.conflict_count, event_insert_count=result.event_insert_count, dimension_insert_count=result.dimension_insert_count, dimension_update_count=result.dimension_update_count, late_event_count=result.late_event_count, processing_duration_ms=result.processing_duration_ms, error_message=result.error_message)
        conn.close()
    if result.status == 'failed':
        raise RuntimeError(result.error_message)
    return result

def _exec(conn, sql: str, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)

def _fetch_all_customer_events(conn, customer_id: str):
    from src.validation import AcceptedEvent
    from datetime import timezone
    sql = '\n        SELECT event_id, customer_id, customer_name, city,\n               event_timestamp, source_file, source_row_number,\n               payload_hash, source_sequence\n        FROM   customer_events\n        WHERE  customer_id = %s\n        ORDER  BY event_timestamp, source_sequence NULLS LAST\n    '
    with conn.cursor() as cur:
        cur.execute(sql, (customer_id,))
        rows = cur.fetchall()
    events = []
    for row in rows:
        ts = row['event_timestamp']
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        events.append(AcceptedEvent(event_id=row['event_id'], customer_id=row['customer_id'], customer_name=row['customer_name'], city=row['city'], event_timestamp=ts, source_file=row['source_file'], source_row_number=row['source_row_number'], payload_hash=row['payload_hash'], source_sequence=row['source_sequence']))
    return events
