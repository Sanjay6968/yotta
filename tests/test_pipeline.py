from pathlib import Path
import psycopg2.extras
import pytest
from src.config import get_config
from src.pipeline import run_pipeline
from src.storage import get_connection
SAMPLE_CSV = Path(__file__).parent.parent / 'data' / 'sample' / 'sample_events.csv'

def _full_reset(db) -> None:
    with db.cursor() as cur:
        cur.execute('TRUNCATE TABLE dim_customer, customer_events, rejected_records, pipeline_runs RESTART IDENTITY CASCADE')

@pytest.fixture
def db():
    try:
        cfg = get_config()
        conn = get_connection(cfg)
        conn.autocommit = True
        conn.cursor_factory = psycopg2.extras.RealDictCursor
    except Exception as e:
        pytest.skip(f'Database unavailable: {e}')
        return
    _full_reset(conn)
    yield conn
    conn.close()

def _q(db, sql, params=None):
    with db.cursor() as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]

def _q1(db, sql, params=None):
    rows = _q(db, sql, params)
    return rows[0] if rows else None

def test_sample_pipeline_runs_successfully(db):
    result = run_pipeline(str(SAMPLE_CSV))
    assert result.status == 'success'
    assert result.input_count == 15
    assert result.accepted_count == 12
    assert result.rejected_count == 3

def test_pipeline_inserts_events_and_creates_dimensions(db):
    result = run_pipeline(str(SAMPLE_CSV))
    assert result.event_insert_count > 0, f'Expected events inserted but got 0 (dup={result.duplicate_count})'
    assert result.dimension_insert_count > 0, f'Expected dim records but got 0'

def test_pipeline_temporal_integrity(db):
    run_pipeline(str(SAMPLE_CSV))
    violations = _q(db, '\n        WITH ordered AS (\n            SELECT customer_id, effective_start, effective_end,\n                   LEAD(effective_start) OVER (\n                       PARTITION BY customer_id ORDER BY effective_start\n                   ) AS next_start\n            FROM   dim_customer\n        )\n        SELECT * FROM ordered\n        WHERE  next_start IS NOT NULL AND effective_end != next_start\n    ')
    assert violations == [], f'Temporal violations: {violations}'

def test_pipeline_one_current_version_per_customer(db):
    run_pipeline(str(SAMPLE_CSV))
    multi = _q(db, '\n        SELECT customer_id, COUNT(*) AS n\n        FROM   dim_customer\n        WHERE  is_current = TRUE\n        GROUP  BY customer_id\n        HAVING COUNT(*) > 1\n    ')
    assert multi == [], f'Multiple current versions: {multi}'

def test_pipeline_rejected_records_written(db):
    result = run_pipeline(str(SAMPLE_CSV))
    count = _q1(db, 'SELECT COUNT(*) AS n FROM rejected_records WHERE run_id = %s', (result.run_id,))
    assert count['n'] >= 3

def test_pipeline_run_recorded_in_pipeline_runs(db):
    result = run_pipeline(str(SAMPLE_CSV))
    run = _q1(db, 'SELECT * FROM pipeline_runs WHERE run_id::text = %s', (result.run_id,))
    assert run is not None
    assert run['status'] == 'success'
    assert run['input_count'] == 15
    assert run['finished_at'] is not None
    assert run['processing_duration_ms'] is not None

def test_pipeline_is_idempotent(db):
    r1 = run_pipeline(str(SAMPLE_CSV))
    r2 = run_pipeline(str(SAMPLE_CSV))
    assert r1.status == 'success'
    assert r2.status == 'success'
    assert r2.event_insert_count == 0
    assert r2.dimension_insert_count == 0
    assert r2.duplicate_count > 0

def test_pipeline_multi_version_customers(db):
    run_pipeline(str(SAMPLE_CSV))
    multi_version = _q(db, '\n        SELECT customer_id, COUNT(*) AS versions\n        FROM   dim_customer\n        GROUP  BY customer_id\n        HAVING COUNT(*) > 1\n    ')
    assert len(multi_version) >= 1, 'Expected at least one customer with multiple SCD versions'
