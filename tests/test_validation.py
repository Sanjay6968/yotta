from datetime import datetime, timezone
import pytest
from src.validation import AcceptedEvent, RejectedEvent, check_schema, compute_hash, validate_row

def _valid_row(**overrides) -> dict:
    base = {'event_id': 'EVT-001', 'customer_id': 'C1', 'customer_name': 'Alice Kumar', 'city': 'Hyderabad', 'event_timestamp': '2024-01-01T00:00:00+00:00', 'source_sequence': '1'}
    return {**base, **overrides}

def test_schema_check_passes_with_all_required_columns():
    cols = ['event_id', 'customer_id', 'customer_name', 'city', 'event_timestamp']
    assert check_schema(cols) == []

def test_schema_check_passes_with_extra_columns():
    cols = ['event_id', 'customer_id', 'customer_name', 'city', 'event_timestamp', 'source_sequence', 'some_extra_column']
    assert check_schema(cols) == []

def test_schema_check_reports_missing_columns():
    cols = ['event_id', 'customer_name', 'city']
    missing = check_schema(cols)
    assert 'customer_id' in missing
    assert 'event_timestamp' in missing

def test_schema_check_empty_columns():
    missing = check_schema([])
    assert set(missing) == {'event_id', 'customer_id', 'customer_name', 'city', 'event_timestamp'}

def test_valid_row_returns_accepted_event():
    result = validate_row(_valid_row(), 'test.csv', 1)
    assert isinstance(result, AcceptedEvent)
    assert result.event_id == 'EVT-001'
    assert result.customer_id == 'C1'
    assert result.customer_name == 'Alice Kumar'
    assert result.city == 'Hyderabad'
    assert result.source_file == 'test.csv'
    assert result.source_row_number == 1
    assert result.source_sequence == 1

def test_valid_row_timestamp_is_utc_datetime():
    result = validate_row(_valid_row(), 'test.csv', 1)
    assert isinstance(result, AcceptedEvent)
    ts = result.event_timestamp
    assert isinstance(ts, datetime)
    assert ts.tzinfo is not None
    assert ts.tzinfo == timezone.utc
    assert ts.year == 2024
    assert ts.month == 1
    assert ts.day == 1

def test_valid_row_with_tz_offset_normalised_to_utc():
    row = _valid_row(event_timestamp='2024-01-01T05:30:00+05:30')
    result = validate_row(row, 'test.csv', 1)
    assert isinstance(result, AcceptedEvent)
    assert result.event_timestamp == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

def test_valid_row_with_z_suffix():
    row = _valid_row(event_timestamp='2024-06-15T12:00:00Z')
    result = validate_row(row, 'test.csv', 1)
    assert isinstance(result, AcceptedEvent)
    assert result.event_timestamp.tzinfo == timezone.utc

def test_valid_row_without_source_sequence():
    row = _valid_row()
    del row['source_sequence']
    result = validate_row(row, 'test.csv', 1)
    assert isinstance(result, AcceptedEvent)
    assert result.source_sequence is None

def test_valid_row_with_empty_source_sequence():
    row = _valid_row(source_sequence='')
    result = validate_row(row, 'test.csv', 1)
    assert isinstance(result, AcceptedEvent)
    assert result.source_sequence is None

def test_missing_event_id_rejected():
    result = validate_row(_valid_row(event_id=''), 'test.csv', 1)
    assert isinstance(result, RejectedEvent)
    assert 'event_id' in result.rejection_reason

def test_missing_customer_id_rejected():
    result = validate_row(_valid_row(customer_id=''), 'test.csv', 2)
    assert isinstance(result, RejectedEvent)
    assert 'customer_id' in result.rejection_reason

def test_missing_customer_name_rejected():
    result = validate_row(_valid_row(customer_name=''), 'test.csv', 3)
    assert isinstance(result, RejectedEvent)
    assert 'customer_name' in result.rejection_reason

def test_missing_city_rejected():
    result = validate_row(_valid_row(city=''), 'test.csv', 4)
    assert isinstance(result, RejectedEvent)
    assert 'city' in result.rejection_reason

def test_missing_event_timestamp_rejected():
    result = validate_row(_valid_row(event_timestamp=''), 'test.csv', 5)
    assert isinstance(result, RejectedEvent)
    assert 'event_timestamp' in result.rejection_reason

def test_malformed_timestamp_rejected():
    row = _valid_row(event_timestamp='not-a-date')
    result = validate_row(row, 'test.csv', 6)
    assert isinstance(result, RejectedEvent)
    assert 'malformed timestamp' in result.rejection_reason
    assert 'not-a-date' in result.rejection_reason

def test_naive_timestamp_rejected():
    row = _valid_row(event_timestamp='2024-01-01T00:00:00')
    result = validate_row(row, 'test.csv', 7)
    assert isinstance(result, RejectedEvent)
    assert 'timezone-naive' in result.rejection_reason

def test_invalid_source_sequence_rejected():
    row = _valid_row(source_sequence='abc')
    result = validate_row(row, 'test.csv', 8)
    assert isinstance(result, RejectedEvent)
    assert 'source_sequence' in result.rejection_reason

def test_multiple_problems_collected_in_single_rejection():
    row = _valid_row(customer_id='', city='', event_timestamp='bad')
    result = validate_row(row, 'test.csv', 9)
    assert isinstance(result, RejectedEvent)
    assert 'customer_id' in result.rejection_reason
    assert 'city' in result.rejection_reason
    assert 'malformed timestamp' in result.rejection_reason

def test_rejected_event_preserves_raw_payload():
    row = _valid_row(customer_id='', event_timestamp='bad-date')
    result = validate_row(row, 'test.csv', 10)
    assert isinstance(result, RejectedEvent)
    assert result.raw_payload['customer_id'] == ''
    assert result.raw_payload['event_timestamp'] == 'bad-date'

def test_whitespace_only_field_treated_as_missing():
    row = _valid_row(customer_id='   ')
    result = validate_row(row, 'test.csv', 11)
    assert isinstance(result, RejectedEvent)
    assert 'customer_id' in result.rejection_reason

def test_hash_is_deterministic():
    h1 = compute_hash('C1', 'Alice Kumar', 'Hyderabad')
    h2 = compute_hash('C1', 'Alice Kumar', 'Hyderabad')
    assert h1 == h2

def test_hash_differs_for_different_city():
    h1 = compute_hash('C1', 'Alice Kumar', 'Hyderabad')
    h2 = compute_hash('C1', 'Alice Kumar', 'Chennai')
    assert h1 != h2

def test_hash_normalises_case():
    h1 = compute_hash('C1', 'Alice Kumar', 'Hyderabad')
    h2 = compute_hash('C1', 'Alice Kumar', 'hyderabad')
    assert h1 == h2

def test_hash_normalises_whitespace():
    h1 = compute_hash('C1', 'Alice Kumar', 'Hyderabad')
    h2 = compute_hash('  C1  ', '  Alice Kumar  ', '  Hyderabad  ')
    assert h1 == h2

def test_hash_is_sha256_length():
    h = compute_hash('C1', 'Alice', 'Delhi')
    assert len(h) == 64
    assert all((c in '0123456789abcdef' for c in h))

def test_hash_in_accepted_event_matches_compute_hash():
    row = _valid_row()
    result = validate_row(row, 'test.csv', 1)
    assert isinstance(result, AcceptedEvent)
    expected = compute_hash('C1', 'Alice Kumar', 'Hyderabad')
    assert result.payload_hash == expected
