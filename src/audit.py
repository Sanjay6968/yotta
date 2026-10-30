from __future__ import annotations
import logging
from datetime import datetime, timezone
from pathlib import Path
import psycopg2.extensions
import psycopg2.extras
from src.config import get_config
from src.storage import get_connection
logger = logging.getLogger(__name__)

def generate_audit_report(output_path: str | Path | None=None) -> str:
    cfg = get_config()
    conn = get_connection(cfg)
    conn.autocommit = True
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    try:
        report = _build_report(conn)
    finally:
        conn.close()
    if output_path is None:
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        output_path = reports_dir / f'audit_report_{ts}.txt'
    Path(output_path).write_text(report, encoding='utf-8')
    logger.info('Audit report written to: %s', output_path)
    return report

def _build_report(conn: psycopg2.extensions.connection) -> str:
    sections = []
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    sections.append(_header(now))
    sections.append(_pipeline_runs_section(conn))
    sections.append(_event_ledger_section(conn))
    sections.append(_dimension_section(conn))
    sections.append(_rejected_section(conn))
    sections.append(_temporal_integrity_section(conn))
    sections.append(_top_customers_section(conn))
    return '\n'.join(sections)

def _header(now: str) -> str:
    return f"\nChronoLedger -- Audit & Reconciliation Report\nGenerated : {now}\n{'=' * 62}".strip()

def _q(conn, sql: str, params=None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]

def _q1(conn, sql: str, params=None) -> dict | None:
    rows = _q(conn, sql, params)
    return rows[0] if rows else None

def _pipeline_runs_section(conn) -> str:
    runs = _q(conn, '\n        SELECT run_id, input_file, started_at, finished_at, status,\n               input_count, accepted_count, rejected_count,\n               duplicate_count, conflict_count,\n               event_insert_count, dimension_insert_count, dimension_update_count,\n               late_event_count, processing_duration_ms, error_message\n        FROM   pipeline_runs\n        ORDER  BY started_at DESC\n        LIMIT  10\n    ')
    lines = ['\n── Pipeline Runs (last 10) ──────────────────────────────────']
    if not runs:
        lines.append('  No runs recorded yet.')
        return '\n'.join(lines)
    for r in runs:
        dur = f"{r['processing_duration_ms']}ms" if r['processing_duration_ms'] else '?'
        lines.append(f"\n  Run  : {r['run_id']}\n  File : {r['input_file']}\n  Time : {r['started_at']}  [{dur}]\n  Status : {r['status'].upper()}")
        if r['status'] == 'success':
            lines.append(f"  Counts -> input:{r['input_count']}  accepted:{r['accepted_count']}  rejected:{r['rejected_count']}  dup:{r['duplicate_count']}  conflict:{r['conflict_count']}\n             events_inserted:{r['event_insert_count']}  dim_versions:{r['dimension_insert_count']}  late:{r['late_event_count']}")
        elif r['status'] == 'failed':
            lines.append(f"  Error: {r['error_message']}")
        lines.append('  ' + '-' * 60)
    return '\n'.join(lines)

def _event_ledger_section(conn) -> str:
    totals = _q1(conn, '\n        SELECT COUNT(*)                                           AS total_events,\n               COUNT(DISTINCT customer_id)                        AS unique_customers,\n               MIN(event_timestamp)                               AS earliest_event,\n               MAX(event_timestamp)                               AS latest_event,\n               MIN(ingested_at)                                   AS first_ingest,\n               MAX(ingested_at)                                   AS last_ingest\n        FROM   customer_events\n    ')
    lines = ['\n── Event Ledger (customer_events) ───────────────────────────']
    if not totals or totals['total_events'] == 0:
        lines.append('  No events in ledger.')
        return '\n'.join(lines)
    lines += [f"  Total events       : {totals['total_events']}", f"  Unique customers   : {totals['unique_customers']}", f"  Earliest event_ts  : {totals['earliest_event']}", f"  Latest event_ts    : {totals['latest_event']}", f"  First ingested     : {totals['first_ingest']}", f"  Last ingested      : {totals['last_ingest']}"]
    return '\n'.join(lines)

def _dimension_section(conn) -> str:
    totals = _q1(conn, '\n        SELECT COUNT(*)                                          AS total_versions,\n               COUNT(DISTINCT customer_id)                       AS total_customers,\n               SUM(CASE WHEN is_current THEN 1 ELSE 0 END)      AS current_versions\n        FROM   dim_customer\n    ')
    avg = _q1(conn, '\n        SELECT ROUND(AVG(cnt), 2) AS avg_versions_per_customer\n        FROM (SELECT COUNT(*) AS cnt FROM dim_customer GROUP BY customer_id) sub\n    ')
    lines = ['\n── SCD Type 2 Dimension (dim_customer) ──────────────────────']
    if not totals or totals['total_versions'] == 0:
        lines.append('  No dimension records yet.')
        return '\n'.join(lines)
    lines += [f"  Total versions     : {totals['total_versions']}", f"  Total customers    : {totals['total_customers']}", f"  Current versions   : {totals['current_versions']}", f"  Avg versions/cust  : {(avg['avg_versions_per_customer'] if avg else 'N/A')}"]
    return '\n'.join(lines)

def _rejected_section(conn) -> str:
    totals = _q1(conn, '\n        SELECT COUNT(*) AS total_rejected,\n               COUNT(DISTINCT run_id) AS runs_with_rejections\n        FROM   rejected_records\n    ')
    top_reasons = _q(conn, '\n        SELECT SUBSTRING(rejection_reason, 1, 80) AS reason_prefix,\n               COUNT(*) AS count\n        FROM   rejected_records\n        GROUP  BY reason_prefix\n        ORDER  BY count DESC\n        LIMIT  5\n    ')
    lines = ['\n── Rejected / Quarantined Records ───────────────────────────']
    if not totals or totals['total_rejected'] == 0:
        lines.append('  No rejected records.')
        return '\n'.join(lines)
    lines += [f"  Total rejected     : {totals['total_rejected']}", f"  Runs with rejects  : {totals['runs_with_rejections']}", '', '  Top rejection reasons:']
    for r in top_reasons:
        lines.append(f"    [{r['count']:>4}] {r['reason_prefix']}")
    return '\n'.join(lines)

def _temporal_integrity_section(conn) -> str:
    violations = _q(conn, '\n        WITH ordered AS (\n            SELECT customer_id, effective_start, effective_end,\n                   LEAD(effective_start) OVER (\n                       PARTITION BY customer_id ORDER BY effective_start\n                   ) AS next_start\n            FROM   dim_customer\n        )\n        SELECT customer_id, effective_start, effective_end, next_start\n        FROM   ordered\n        WHERE  next_start IS NOT NULL\n          AND  effective_end != next_start\n    ')
    multi_current = _q(conn, '\n        SELECT customer_id, COUNT(*) AS current_count\n        FROM   dim_customer\n        WHERE  is_current = TRUE\n        GROUP  BY customer_id\n        HAVING COUNT(*) > 1\n    ')
    lines = ['\n── Temporal Integrity Check ─────────────────────────────────']
    if not violations and (not multi_current):
        lines.append('  OK: No interval violations detected.')
        lines.append('  OK: No customers with multiple current versions.')
    else:
        if violations:
            lines.append(f'  FAIL - INTERVAL VIOLATIONS: {len(violations)} found')
            for v in violations[:5]:
                lines.append(f"    customer={v['customer_id']} end={v['effective_end']} != next_start={v['next_start']}")
        if multi_current:
            lines.append(f'  FAIL - MULTIPLE CURRENT VERSIONS: {len(multi_current)} customers')
            for v in multi_current[:5]:
                lines.append(f"    customer={v['customer_id']} count={v['current_count']}")
    return '\n'.join(lines)

def _top_customers_section(conn) -> str:
    rows = _q(conn, '\n        SELECT d.customer_id,\n               d.customer_name,\n               d.city                             AS current_city,\n               d.effective_start                  AS current_since,\n               h.version_count\n        FROM   dim_customer d\n        JOIN  (SELECT customer_id, COUNT(*) AS version_count\n               FROM   dim_customer GROUP BY customer_id) h\n          ON   d.customer_id = h.customer_id\n        WHERE  d.is_current = TRUE\n        ORDER  BY h.version_count DESC, d.customer_id\n        LIMIT  10\n    ')
    lines = ['\n── Current Customer Snapshot (top 10 by versions) ───────────']
    if not rows:
        lines.append('  No current customer records.')
        return '\n'.join(lines)
    lines.append(f"  {'Customer':<12} {'Name':<20} {'City':<15} {'Current Since':<25} Versions")
    lines.append('  ' + '-' * 80)
    for r in rows:
        lines.append(f"  {r['customer_id']:<12} {r['customer_name']:<20} {r['current_city']:<15} {str(r['current_since']):<25} {r['version_count']}")
    return '\n'.join(lines)
