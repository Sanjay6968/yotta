from datetime import datetime, timezone
import pytest
from src.reconstruction import DimRecord, reconstruct_customer_history
from src.validation import AcceptedEvent

def _ts(year: int, month: int=1, day: int=1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)

def _event(event_id: str, customer_id: str='C1', customer_name: str='Alice', city: str='Hyderabad', event_timestamp: datetime | None=None, payload_hash: str | None=None, source_sequence: int | None=None) -> AcceptedEvent:
    if event_timestamp is None:
        event_timestamp = _ts(2024)
    if payload_hash is None:
        payload_hash = f"hash_{city.lower().replace(' ', '_')}"
    return AcceptedEvent(event_id=event_id, customer_id=customer_id, customer_name=customer_name, city=city, event_timestamp=event_timestamp, source_file='test.csv', source_row_number=1, payload_hash=payload_hash, source_sequence=source_sequence)
_RUN_ID = 'test-run-reconstruction'

def test_empty_events_returns_empty():
    result = reconstruct_customer_history([], run_id=_RUN_ID)
    assert result == []

def test_single_event_produces_one_current_record():
    event = _event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1))
    result = reconstruct_customer_history([event], run_id=_RUN_ID)
    assert len(result) == 1
    r = result[0]
    assert r.is_current is True
    assert r.effective_end is None
    assert r.effective_start == _ts(2024, 1, 1)
    assert r.city == 'Hyderabad'

def test_two_distinct_events_produce_two_records():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E2', city='Bangalore', event_timestamp=_ts(2024, 3, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    assert len(result) == 2
    assert result[0].city == 'Hyderabad'
    assert result[0].effective_start == _ts(2024, 1, 1)
    assert result[0].effective_end == _ts(2024, 3, 1)
    assert result[0].is_current is False
    assert result[1].city == 'Bangalore'
    assert result[1].effective_start == _ts(2024, 3, 1)
    assert result[1].effective_end is None
    assert result[1].is_current is True

def test_three_events_produce_correct_intervals():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E2', city='Chennai', event_timestamp=_ts(2024, 2, 1)), _event('E3', city='Bangalore', event_timestamp=_ts(2024, 3, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    assert len(result) == 3
    assert result[0].effective_end == _ts(2024, 2, 1)
    assert result[1].effective_start == _ts(2024, 2, 1)
    assert result[1].effective_end == _ts(2024, 3, 1)
    assert result[2].effective_end is None

def test_events_sorted_by_business_time_not_arrival_order():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E3', city='Bangalore', event_timestamp=_ts(2024, 3, 1)), _event('E2', city='Chennai', event_timestamp=_ts(2024, 2, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    cities = [r.city for r in result]
    assert cities == ['Hyderabad', 'Chennai', 'Bangalore']

def test_late_arriving_event_restructures_history():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E3', city='Bangalore', event_timestamp=_ts(2024, 3, 1)), _event('E2', city='Chennai', event_timestamp=_ts(2024, 2, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    assert len(result) == 3
    assert result[0].effective_end == _ts(2024, 2, 1)
    assert result[1].effective_start == _ts(2024, 2, 1)
    assert result[1].effective_end == _ts(2024, 3, 1)

def test_source_sequence_breaks_timestamp_tie():
    e1 = _event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1), payload_hash='hash_hyd', source_sequence=1)
    e2 = _event('E2', city='Bangalore', event_timestamp=_ts(2024, 1, 1), payload_hash='hash_blr', source_sequence=2)
    result = reconstruct_customer_history([e1, e2], run_id=_RUN_ID)
    assert len(result) == 1
    assert result[0].city == 'Bangalore'
    assert result[0].is_current is True
    assert result[0].effective_end is None

def test_consecutive_identical_states_collapsed():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1), payload_hash='same'), _event('E2', city='Hyderabad', event_timestamp=_ts(2024, 2, 1), payload_hash='same')]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    assert len(result) == 1
    assert result[0].effective_start == _ts(2024, 1, 1)
    assert result[0].is_current is True

def test_state_changes_then_reverts_not_collapsed():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1), payload_hash='h1'), _event('E2', city='Bangalore', event_timestamp=_ts(2024, 2, 1), payload_hash='h2'), _event('E3', city='Hyderabad', event_timestamp=_ts(2024, 3, 1), payload_hash='h1')]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    assert len(result) == 3

def test_all_events_same_state_produces_one_record():
    events = [_event(f'E{i}', city='Delhi', event_timestamp=_ts(2024, i, 1), payload_hash='delhi') for i in range(1, 6)]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    assert len(result) == 1

def test_exactly_one_current_record(events_factory=None):
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E2', city='Chennai', event_timestamp=_ts(2024, 3, 1)), _event('E3', city='Bangalore', event_timestamp=_ts(2024, 6, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    current_count = sum((1 for r in result if r.is_current))
    assert current_count == 1

def test_exactly_one_none_effective_end():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E2', city='Bangalore', event_timestamp=_ts(2024, 6, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    none_count = sum((1 for r in result if r.effective_end is None))
    assert none_count == 1

def test_intervals_are_contiguous():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E2', city='Chennai', event_timestamp=_ts(2024, 3, 1)), _event('E3', city='Bangalore', event_timestamp=_ts(2024, 6, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    for i in range(len(result) - 1):
        assert result[i].effective_end == result[i + 1].effective_start, f'Gap between record {i} and {i + 1}'

def test_historical_effective_end_after_start():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E2', city='Chennai', event_timestamp=_ts(2024, 3, 1))]
    result = reconstruct_customer_history(events, run_id=_RUN_ID)
    for rec in result:
        if rec.effective_end is not None:
            assert rec.effective_end > rec.effective_start

def test_record_hash_matches_event_payload_hash():
    event = _event('E1', city='Pune', payload_hash='sha256_of_pune')
    result = reconstruct_customer_history([event], run_id=_RUN_ID)
    assert result[0].record_hash == 'sha256_of_pune'

def test_run_id_propagated_to_all_records():
    events = [_event('E1', city='Hyderabad', event_timestamp=_ts(2024, 1, 1)), _event('E2', city='Chennai', event_timestamp=_ts(2024, 3, 1))]
    result = reconstruct_customer_history(events, run_id='my-special-run')
    for rec in result:
        assert rec.run_id == 'my-special-run'

def test_multi_customer_events_raises_value_error():
    events = [_event('E1', customer_id='C1'), _event('E2', customer_id='C2')]
    with pytest.raises(ValueError, match='multiple customers'):
        reconstruct_customer_history(events, run_id=_RUN_ID)
