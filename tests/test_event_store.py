import json
from datetime import datetime, timezone
import psycopg2
import psycopg2.extras
import pytest
from src.config import get_config
from src.event_store import fetch_ledger_entries, insert_events, insert_rejected_records
from src.storage import get_connection
from src.validation import AcceptedEvent, RejectedEvent
_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)
_RUN_ID = 'test-run-00000000'

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

def _event(event_id: str='E-STORE-001', customer_id: str='C1', payload_hash: str='aaaa1234', source_row: int=1) -> AcceptedEvent:
    return AcceptedEvent(event_id=event_id, customer_id=customer_id, customer_name='Test User', city='Hyderabad', event_timestamp=_TS, source_file='test_store.csv', source_row_number=source_row, payload_hash=payload_hash, source_sequence=None)

def _rejected(source_row: int=1, reason: str='test rejection') -> RejectedEvent:
    return RejectedEvent(source_file='test_store.csv', source_row_number=source_row, raw_payload={'event_id': 'E-BAD', 'reason': reason}, rejection_reason=reason)

def test_fetch_empty_ledger_returns_empty_dict(db_conn):
    result = fetch_ledger_entries(db_conn, ['E-NOTEXIST-1', 'E-NOTEXIST-2'])
    assert result == {}

def test_fetch_returns_correct_hash_for_known_event(db_conn):
    event = _event('E-FETCH-001', payload_hash='deadbeef')
    insert_events(db_conn, [event], run_id=_RUN_ID)
    result = fetch_ledger_entries(db_conn, ['E-FETCH-001'])
    assert result == {'E-FETCH-001': 'deadbeef'}

def test_fetch_ignores_unrequested_event_ids(db_conn):
    e1 = _event('E-FETCH-A', payload_hash='hash_A')
    e2 = _event('E-FETCH-B', payload_hash='hash_B')
    insert_events(db_conn, [e1, e2], run_id=_RUN_ID)
    result = fetch_ledger_entries(db_conn, ['E-FETCH-A'])
    assert 'E-FETCH-A' in result
    assert 'E-FETCH-B' not in result

def test_fetch_with_empty_list_returns_empty(db_conn):
    result = fetch_ledger_entries(db_conn, [])
    assert result == {}

def test_insert_events_returns_correct_count(db_conn):
    events = [_event('E-INS-001'), _event('E-INS-002'), _event('E-INS-003')]
    count = insert_events(db_conn, events, run_id=_RUN_ID)
    assert count == 3

def test_insert_events_empty_list_returns_zero(db_conn):
    count = insert_events(db_conn, [], run_id=_RUN_ID)
    assert count == 0

def test_insert_duplicate_event_id_raises_integrity_error(db_conn):
    event = _event('E-DUP-CONSTRAINT')
    insert_events(db_conn, [event], run_id=_RUN_ID)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        insert_events(db_conn, [event], run_id=_RUN_ID)

def test_insert_events_stores_correct_fields(db_conn):
    event = AcceptedEvent(event_id='E-FIELDS-001', customer_id='C-FIELDS', customer_name='Field Tester', city='Bengaluru', event_timestamp=_TS, source_file='field_test.csv', source_row_number=42, payload_hash='cafebabe', source_sequence=7)
    insert_events(db_conn, [event], run_id=_RUN_ID)
    with db_conn.cursor() as cur:
        cur.execute('SELECT * FROM customer_events WHERE event_id = %s', ('E-FIELDS-001',))
        row = cur.fetchone()
    assert row is not None
    assert row['customer_id'] == 'C-FIELDS'
    assert row['customer_name'] == 'Field Tester'
    assert row['city'] == 'Bengaluru'
    assert row['payload_hash'] == 'cafebabe'
    assert row['source_row_number'] == 42
    assert row['source_sequence'] == 7
    assert row['run_id'] == _RUN_ID

def test_insert_rejected_records_returns_correct_count(db_conn):
    records = [_rejected(1, 'bad row 1'), _rejected(2, 'bad row 2')]
    count = insert_rejected_records(db_conn, records, run_id=_RUN_ID)
    assert count == 2

def test_insert_rejected_records_empty_list_returns_zero(db_conn):
    count = insert_rejected_records(db_conn, [], run_id=_RUN_ID)
    assert count == 0

def test_insert_rejected_stores_raw_payload_as_jsonb(db_conn):
    payload = {'event_id': 'E-BAD', 'customer_id': '', 'city': '??'}
    record = RejectedEvent(source_file='jsonb_test.csv', source_row_number=3, raw_payload=payload, rejection_reason='missing customer_id')
    insert_rejected_records(db_conn, [record], run_id=_RUN_ID)
    with db_conn.cursor() as cur:
        cur.execute('SELECT raw_payload, rejection_reason FROM rejected_records WHERE run_id = %s ORDER BY reject_id DESC LIMIT 1', (_RUN_ID,))
        row = cur.fetchone()
    assert row is not None
    assert isinstance(row['raw_payload'], dict)
    assert row['raw_payload']['event_id'] == 'E-BAD'
    assert row['rejection_reason'] == 'missing customer_id'

def test_round_trip_insert_then_fetch(db_conn):
    events = [_event('E-RT-001', payload_hash='hash1'), _event('E-RT-002', payload_hash='hash2'), _event('E-RT-003', payload_hash='hash3')]
    insert_events(db_conn, events, run_id=_RUN_ID)
    ledger = fetch_ledger_entries(db_conn, ['E-RT-001', 'E-RT-002', 'E-RT-003'])
    assert ledger == {'E-RT-001': 'hash1', 'E-RT-002': 'hash2', 'E-RT-003': 'hash3'}
