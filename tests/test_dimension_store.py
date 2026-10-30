from datetime import datetime, timezone
import psycopg2.extras
import pytest
from src.config import get_config
from src.dimension_store import delete_customer_dim_records, fetch_current_dim_record, fetch_customer_dim_history, insert_dim_records, replace_customer_history
from src.reconstruction import DimRecord
from src.storage import get_connection
_RUN_ID = 'test-run-dimstore'
_TS = datetime

def _ts(year: int, month: int=1, day: int=1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)

@pytest.fixture
def db_conn():
    try:
        cfg = get_config()
        conn = get_connection(cfg)
        conn.autocommit = False
        conn.cursor_factory = psycopg2.extras.RealDictCursor
    except Exception as e:
        pytest.skip(f'Database unavailable: {e}')
        return
    yield conn
    conn.rollback()
    conn.close()

def _record(customer_id: str='C-DIM-1', city: str='Hyderabad', effective_start: datetime | None=None, effective_end: datetime | None=None, is_current: bool=True, record_hash: str='hash_hyd') -> DimRecord:
    if effective_start is None:
        effective_start = _ts(2024, 1, 1)
    return DimRecord(customer_id=customer_id, customer_name='Test User', city=city, effective_start=effective_start, effective_end=effective_end, is_current=is_current, record_hash=record_hash, run_id=_RUN_ID)

def _history_two_versions(customer_id: str='C-DIM-HIST') -> list[DimRecord]:
    return [_record(customer_id=customer_id, city='Hyderabad', effective_start=_ts(2024, 1, 1), effective_end=_ts(2024, 3, 1), is_current=False, record_hash='hash_hyd'), _record(customer_id=customer_id, city='Bangalore', effective_start=_ts(2024, 3, 1), effective_end=None, is_current=True, record_hash='hash_blr')]

def test_fetch_current_returns_none_for_new_customer(db_conn):
    result = fetch_current_dim_record(db_conn, 'C-NEW-9999')
    assert result is None

def test_fetch_current_returns_correct_row(db_conn):
    records = [_record(customer_id='C-FETCH-CURR', city='Pune', record_hash='hash_pune')]
    insert_dim_records(db_conn, records)
    result = fetch_current_dim_record(db_conn, 'C-FETCH-CURR')
    assert result is not None
    assert result['city'] == 'Pune'
    assert result['is_current'] is True

def test_fetch_current_ignores_historical_rows(db_conn):
    records = _history_two_versions(customer_id='C-FETCH-CURR2')
    insert_dim_records(db_conn, records)
    result = fetch_current_dim_record(db_conn, 'C-FETCH-CURR2')
    assert result['city'] == 'Bangalore'

def test_fetch_history_returns_all_rows_ordered(db_conn):
    records = _history_two_versions(customer_id='C-FETCH-HIST')
    insert_dim_records(db_conn, records)
    history = fetch_customer_dim_history(db_conn, 'C-FETCH-HIST')
    assert len(history) == 2
    assert history[0]['city'] == 'Hyderabad'
    assert history[1]['city'] == 'Bangalore'

def test_fetch_history_returns_empty_for_unknown_customer(db_conn):
    history = fetch_customer_dim_history(db_conn, 'C-UNKNOWN-9999')
    assert history == []

def test_delete_returns_count_of_deleted_rows(db_conn):
    records = _history_two_versions(customer_id='C-DEL-1')
    insert_dim_records(db_conn, records)
    deleted = delete_customer_dim_records(db_conn, 'C-DEL-1')
    assert deleted == 2

def test_delete_returns_zero_for_unknown_customer(db_conn):
    deleted = delete_customer_dim_records(db_conn, 'C-UNKNOWN-DEL')
    assert deleted == 0

def test_delete_removes_all_rows(db_conn):
    records = _history_two_versions(customer_id='C-DEL-2')
    insert_dim_records(db_conn, records)
    delete_customer_dim_records(db_conn, 'C-DEL-2')
    history = fetch_customer_dim_history(db_conn, 'C-DEL-2')
    assert history == []

def test_insert_dim_records_returns_correct_count(db_conn):
    records = _history_two_versions(customer_id='C-INS-1')
    count = insert_dim_records(db_conn, records)
    assert count == 2

def test_insert_dim_records_empty_list_returns_zero(db_conn):
    count = insert_dim_records(db_conn, [])
    assert count == 0

def test_insert_dim_records_stores_correct_fields(db_conn):
    rec = _record(customer_id='C-FIELDS-DIM', city='Kolkata', effective_start=_ts(2024, 6, 1), effective_end=None, is_current=True, record_hash='hash_kolkata')
    insert_dim_records(db_conn, [rec])
    history = fetch_customer_dim_history(db_conn, 'C-FIELDS-DIM')
    assert len(history) == 1
    row = history[0]
    assert row['city'] == 'Kolkata'
    assert row['record_hash'] == 'hash_kolkata'
    assert row['is_current'] is True
    assert row['effective_end'] is None
    assert row['run_id'] == _RUN_ID

def test_partial_unique_index_rejects_two_current_rows(db_conn):
    import psycopg2
    r1 = _record(customer_id='C-UNIQUE-TEST', city='Hyderabad', is_current=True)
    r2 = _record(customer_id='C-UNIQUE-TEST', city='Bangalore', is_current=True, record_hash='hash_blr2')
    insert_dim_records(db_conn, [r1])
    with pytest.raises(psycopg2.errors.UniqueViolation):
        insert_dim_records(db_conn, [r2])

def test_replace_new_customer(db_conn):
    records = _history_two_versions(customer_id='C-REPLACE-NEW')
    deleted, inserted = replace_customer_history(db_conn, 'C-REPLACE-NEW', records)
    assert deleted == 0
    assert inserted == 2

def test_replace_existing_customer(db_conn):
    initial = [_record(customer_id='C-REPLACE-EX', city='Hyderabad')]
    replace_customer_history(db_conn, 'C-REPLACE-EX', initial)
    updated = _history_two_versions(customer_id='C-REPLACE-EX')
    deleted, inserted = replace_customer_history(db_conn, 'C-REPLACE-EX', updated)
    assert deleted == 1
    assert inserted == 2
    history = fetch_customer_dim_history(db_conn, 'C-REPLACE-EX')
    assert len(history) == 2

def test_replace_leaves_other_customers_untouched(db_conn):
    b_records = [_record(customer_id='C-OTHER-B', city='Mumbai', record_hash='hash_mum')]
    insert_dim_records(db_conn, b_records)
    a_records = _history_two_versions(customer_id='C-REPLACE-A')
    replace_customer_history(db_conn, 'C-REPLACE-A', a_records)
    b_history = fetch_customer_dim_history(db_conn, 'C-OTHER-B')
    assert len(b_history) == 1
    assert b_history[0]['city'] == 'Mumbai'
