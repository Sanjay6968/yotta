from datetime import datetime, timezone
import pytest
from src.deduplication import classify_events
from src.validation import AcceptedEvent
_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)

def _event(event_id: str='E001', customer_id: str='C1', customer_name: str='Alice', city: str='Hyderabad', payload_hash: str='aaaa', source_row_number: int=1) -> AcceptedEvent:
    return AcceptedEvent(event_id=event_id, customer_id=customer_id, customer_name=customer_name, city=city, event_timestamp=_TS, source_file='test.csv', source_row_number=source_row_number, payload_hash=payload_hash, source_sequence=None)

def test_empty_batch_returns_empty_result():
    result = classify_events([], ledger={})
    assert result.new_count == 0
    assert result.duplicate_count == 0
    assert result.conflict_count == 0

def test_all_new_events_on_empty_ledger():
    events = [_event('E001'), _event('E002'), _event('E003')]
    result = classify_events(events, ledger={})
    assert result.new_count == 3
    assert result.duplicate_count == 0
    assert result.conflict_count == 0
    ids = [e.event_id for e in result.new_events]
    assert ids == ['E001', 'E002', 'E003']

def test_exact_duplicate_against_ledger():
    event = _event('E001', payload_hash='aaaa')
    ledger = {'E001': 'aaaa'}
    result = classify_events([event], ledger=ledger)
    assert result.new_count == 0
    assert result.duplicate_count == 1
    assert result.conflict_count == 0
    assert result.duplicates[0].event_id == 'E001'

def test_conflict_against_ledger():
    new_arrival = _event('E001', payload_hash='bbbb')
    ledger = {'E001': 'aaaa'}
    result = classify_events([new_arrival], ledger=ledger)
    assert result.new_count == 0
    assert result.duplicate_count == 0
    assert result.conflict_count == 1

def test_conflict_reason_mentions_event_id():
    event = _event('E-CONFLICT-99', payload_hash='new_hash')
    ledger = {'E-CONFLICT-99': 'old_hash'}
    result = classify_events([event], ledger=ledger)
    reason = result.conflicts[0].rejection_reason
    assert 'E-CONFLICT-99' in reason

def test_conflict_rejected_event_preserves_source_row():
    event = _event('E001', payload_hash='new', source_row_number=7)
    ledger = {'E001': 'old'}
    result = classify_events([event], ledger=ledger)
    assert result.conflicts[0].source_row_number == 7

def test_mixed_batch():
    events = [_event('E001', payload_hash='aaa'), _event('E002', payload_hash='bbb'), _event('E003', payload_hash='new'), _event('E004', payload_hash='ddd')]
    ledger = {'E002': 'bbb', 'E003': 'old'}
    result = classify_events(events, ledger=ledger)
    assert result.new_count == 2
    assert result.duplicate_count == 1
    assert result.conflict_count == 1
    new_ids = {e.event_id for e in result.new_events}
    assert new_ids == {'E001', 'E004'}

def test_within_batch_duplicate():
    e1 = _event('E001', payload_hash='same', source_row_number=1)
    e2 = _event('E001', payload_hash='same', source_row_number=2)
    result = classify_events([e1, e2], ledger={})
    assert result.new_count == 1
    assert result.duplicate_count == 1
    assert result.conflict_count == 0
    assert result.new_events[0].event_id == 'E001'

def test_within_batch_conflict():
    e1 = _event('E001', payload_hash='hash_A', source_row_number=1)
    e2 = _event('E001', payload_hash='hash_B', source_row_number=2)
    result = classify_events([e1, e2], ledger={})
    assert result.new_count == 1
    assert result.duplicate_count == 0
    assert result.conflict_count == 1

def test_ledger_not_mutated_by_caller():
    ledger = {'E001': 'aaaa'}
    original_ledger = dict(ledger)
    classify_events([_event('E002', payload_hash='bbbb')], ledger=ledger)
    assert ledger == original_ledger

def test_many_duplicates_count_is_accurate():
    events = [_event(f'E{i:03d}', payload_hash='same') for i in range(50)]
    ledger = {f'E{i:03d}': 'same' for i in range(50)}
    result = classify_events(events, ledger=ledger)
    assert result.new_count == 0
    assert result.duplicate_count == 50
    assert result.conflict_count == 0

def test_counts_sum_to_input_length():
    events = [_event('E001', payload_hash='new'), _event('E002', payload_hash='same'), _event('E003', payload_hash='new2'), _event('E004', payload_hash='conflict_new')]
    ledger = {'E002': 'same', 'E004': 'conflict_old'}
    result = classify_events(events, ledger=ledger)
    total = result.new_count + result.duplicate_count + result.conflict_count
    assert total == len(events)
