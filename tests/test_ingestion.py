import csv
import io
import pathlib
import tempfile
import pytest
from src.ingestion import IngestionResult, ingest_file
SAMPLE_CSV = pathlib.Path(__file__).parent.parent / 'data' / 'sample' / 'sample_events.csv'

def _write_temp_csv(rows: list[dict], fieldnames: list[str]) -> str:
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8', newline='')
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    tmp.flush()
    tmp.close()
    return tmp.name
VALID_FIELDNAMES = ['event_id', 'customer_id', 'customer_name', 'city', 'event_timestamp', 'source_sequence']

def _valid_row(**overrides) -> dict:
    base = {'event_id': 'E-TEST-001', 'customer_id': 'C99', 'customer_name': 'Test User', 'city': 'Hyderabad', 'event_timestamp': '2024-01-01T00:00:00+00:00', 'source_sequence': '1'}
    return {**base, **overrides}

def test_sample_file_exists():
    assert SAMPLE_CSV.exists(), f'Sample file missing: {SAMPLE_CSV}'

def test_sample_file_ingestion_counts():
    result = ingest_file(SAMPLE_CSV)
    assert result.schema_error == '', f'Unexpected schema error: {result.schema_error}'
    assert result.input_count == 15
    assert result.rejected_count == 3
    assert result.accepted_count == 12

def test_sample_file_rejected_rows_have_reasons():
    result = ingest_file(SAMPLE_CSV)
    for r in result.rejected:
        assert r.rejection_reason, f'Row {r.source_row_number} has no rejection reason'
        assert r.raw_payload, f'Row {r.source_row_number} has no raw payload'

def test_sample_file_rejected_rows_preserve_source_info():
    result = ingest_file(SAMPLE_CSV)
    for r in result.rejected:
        assert r.source_file == str(SAMPLE_CSV)
        assert r.source_row_number > 0

def test_missing_required_column_rejects_entire_batch():
    bad_fieldnames = ['event_id', 'customer_name', 'city', 'event_timestamp']
    bad_row = {'event_id': 'E-SCHEMA-TEST', 'customer_name': 'Test User', 'city': 'Delhi', 'event_timestamp': '2024-01-01T00:00:00+00:00'}
    path = _write_temp_csv([bad_row], bad_fieldnames)
    result = ingest_file(path)
    assert result.schema_error != ''
    assert 'customer_id' in result.schema_error
    assert result.accepted_count == 0
    assert result.rejected_count == 0
    assert result.input_count == 0

def test_empty_file_returns_zero_counts():
    path = _write_temp_csv([], VALID_FIELDNAMES)
    result = ingest_file(path)
    assert result.schema_error == ''
    assert result.input_count == 0
    assert result.accepted_count == 0
    assert result.rejected_count == 0

def test_file_not_found_raises():
    with pytest.raises(FileNotFoundError):
        ingest_file('/nonexistent/path/to/file.csv')

def test_single_valid_row_accepted():
    path = _write_temp_csv([_valid_row()], VALID_FIELDNAMES)
    result = ingest_file(path)
    assert result.input_count == 1
    assert result.accepted_count == 1
    assert result.rejected_count == 0
    event = result.accepted[0]
    assert event.event_id == 'E-TEST-001'
    assert event.customer_id == 'C99'

def test_all_invalid_rows_all_rejected():
    rows = [_valid_row(event_id='', customer_id=''), _valid_row(event_timestamp='bad-date')]
    path = _write_temp_csv(rows, VALID_FIELDNAMES)
    result = ingest_file(path)
    assert result.input_count == 2
    assert result.accepted_count == 0
    assert result.rejected_count == 2

def test_ingestion_result_source_file_recorded():
    path = _write_temp_csv([_valid_row()], VALID_FIELDNAMES)
    result = ingest_file(path)
    assert result.source_file == path

def test_accepted_events_have_payload_hash():
    path = _write_temp_csv([_valid_row()], VALID_FIELDNAMES)
    result = ingest_file(path)
    assert result.accepted_count == 1
    assert len(result.accepted[0].payload_hash) == 64

def test_accepted_events_timestamp_is_utc():
    from datetime import timezone
    path = _write_temp_csv([_valid_row()], VALID_FIELDNAMES)
    result = ingest_file(path)
    ts = result.accepted[0].event_timestamp
    assert ts.tzinfo is not None
    assert ts.tzinfo == timezone.utc

def test_source_row_numbers_are_correct():
    rows = [_valid_row(event_id=f'E{i}') for i in range(5)]
    path = _write_temp_csv(rows, VALID_FIELDNAMES)
    result = ingest_file(path)
    assert result.accepted_count == 5
    for i, event in enumerate(result.accepted, start=1):
        assert event.source_row_number == i
