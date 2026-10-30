import uuid
from datetime import datetime, timezone
import psycopg2
import pytest
from src.config import get_config
from src.storage import execute, fetch_all_dicts, get_connection, init_schema, transaction, verify_connection

@pytest.fixture(scope='session')
def cfg():
    return get_config()

@pytest.fixture(scope='session')
def db_conn(cfg):
    conn = get_connection(cfg)
    init_schema(conn)
    yield conn
    conn.close()

@pytest.fixture
def clean_conn(db_conn):
    with db_conn.cursor() as cur:
        cur.execute('SAVEPOINT test_savepoint')
    try:
        yield db_conn
    finally:
        with db_conn.cursor() as cur:
            cur.execute('ROLLBACK TO SAVEPOINT test_savepoint')
            cur.execute('RELEASE SAVEPOINT test_savepoint')

def test_connection_is_alive(db_conn):
    assert verify_connection(db_conn) is True

def test_schema_tables_exist(db_conn):
    rows = fetch_all_dicts(db_conn, "\n        SELECT tablename\n        FROM pg_tables\n        WHERE schemaname = 'public'\n          AND tablename IN (\n              'pipeline_runs', 'customer_events',\n              'dim_customer', 'rejected_records'\n          )\n        ORDER BY tablename\n        ")
    table_names = {r['tablename'] for r in rows}
    assert table_names == {'pipeline_runs', 'customer_events', 'dim_customer', 'rejected_records'}

def test_dim_customer_check_constraint_rejects_invalid_dates(clean_conn):
    now = datetime.now(timezone.utc)
    with pytest.raises(psycopg2.errors.CheckViolation):
        execute(clean_conn, '\n            INSERT INTO dim_customer\n              (customer_id, customer_name, city,\n               effective_start, effective_end, is_current,\n               record_hash, created_at, run_id)\n            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)\n            ', ('C1', 'Alice', 'Mumbai', now, now, False, 'fakehash', now, str(uuid.uuid4())))

def test_dim_customer_partial_unique_index_prevents_two_current(clean_conn):
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    execute(clean_conn, '\n        INSERT INTO dim_customer\n          (customer_id, customer_name, city,\n           effective_start, effective_end, is_current,\n           record_hash, created_at, run_id)\n        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)\n        ', ('C99', 'Test User', 'Delhi', now, None, True, 'hash1', now, run_id))
    with pytest.raises(psycopg2.errors.UniqueViolation):
        execute(clean_conn, '\n            INSERT INTO dim_customer\n              (customer_id, customer_name, city,\n               effective_start, effective_end, is_current,\n               record_hash, created_at, run_id)\n            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)\n            ', ('C99', 'Test User', 'Chennai', now, None, True, 'hash2', now, run_id))

def test_dim_customer_allows_multiple_historical_rows(clean_conn):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    for i in range(3):
        start = now + timedelta(days=i)
        end = now + timedelta(days=i + 1)
        execute(clean_conn, '\n            INSERT INTO dim_customer\n              (customer_id, customer_name, city,\n               effective_start, effective_end, is_current,\n               record_hash, created_at, run_id)\n            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)\n            ', ('C98', f'User{i}', 'Bangalore', start, end, False, f'hash{i}', now, run_id))
    rows = fetch_all_dicts(clean_conn, "SELECT COUNT(*) as cnt FROM dim_customer WHERE customer_id = 'C98'")
    assert rows[0]['cnt'] == 3

def test_pipeline_runs_status_check_constraint(clean_conn):
    now = datetime.now(timezone.utc)
    with pytest.raises(psycopg2.errors.CheckViolation):
        execute(clean_conn, 'INSERT INTO pipeline_runs (run_id, started_at, status) VALUES (%s, %s, %s)', (str(uuid.uuid4()), now, 'invalid_status'))

def test_customer_events_primary_key_prevents_duplicate_event_id(clean_conn):
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    execute(clean_conn, '\n        INSERT INTO customer_events\n          (event_id, customer_id, customer_name, city,\n           event_timestamp, source_file, ingested_at, payload_hash)\n        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)\n        ', ('EVT-001', 'C1', 'Alice', 'Hyderabad', now, 'test.csv', now, 'hash1'))
    with pytest.raises(psycopg2.errors.UniqueViolation):
        execute(clean_conn, '\n            INSERT INTO customer_events\n              (event_id, customer_id, customer_name, city,\n               event_timestamp, source_file, ingested_at, payload_hash)\n            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)\n            ', ('EVT-001', 'C1', 'Alice', 'Hyderabad', now, 'test.csv', now, 'hash1'))

def test_init_schema_is_idempotent(db_conn):
    init_schema(db_conn)
