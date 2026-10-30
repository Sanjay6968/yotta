from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from src.validation import AcceptedEvent
logger = logging.getLogger(__name__)

@dataclass
class DimRecord:
    customer_id: str
    customer_name: str
    city: str
    effective_start: datetime
    effective_end: Optional[datetime]
    is_current: bool
    record_hash: str
    run_id: str

def reconstruct_customer_history(events: list[AcceptedEvent], run_id: str) -> list[DimRecord]:
    if not events:
        return []
    customer_ids = {e.customer_id for e in events}
    if len(customer_ids) > 1:
        raise ValueError(f'reconstruct_customer_history received events for multiple customers: {customer_ids}. Call this function once per customer.')
    sorted_events = sorted(events, key=lambda e: (e.event_timestamp, e.source_sequence if e.source_sequence is not None else -1))
    logger.debug('Reconstruction: customer_id=%s events=%d', sorted_events[0].customer_id, len(sorted_events))
    distinct_events: list[AcceptedEvent] = []
    last_hash: str | None = None
    for event in sorted_events:
        if event.payload_hash == last_hash:
            logger.debug('Collapsed identical state: event_id=%s hash=%s', event.event_id, event.payload_hash)
        elif distinct_events and distinct_events[-1].event_timestamp == event.event_timestamp and (distinct_events[-1].payload_hash != event.payload_hash):
            logger.debug('Same-timestamp supersede: event_id=%s supersedes event_id=%s at %s', event.event_id, distinct_events[-1].event_id, event.event_timestamp)
            distinct_events[-1] = event
            last_hash = event.payload_hash
        else:
            distinct_events.append(event)
            last_hash = event.payload_hash
    records: list[DimRecord] = []
    for i, event in enumerate(distinct_events):
        is_last = i == len(distinct_events) - 1
        effective_end = None if is_last else distinct_events[i + 1].event_timestamp
        records.append(DimRecord(customer_id=event.customer_id, customer_name=event.customer_name, city=event.city, effective_start=event.event_timestamp, effective_end=effective_end, is_current=is_last, record_hash=event.payload_hash, run_id=run_id))
    _validate_history(records)
    logger.info('Reconstruction complete: customer_id=%s versions=%d', sorted_events[0].customer_id, len(records))
    return records

def _validate_history(records: list[DimRecord]) -> None:
    if not records:
        return
    errors: list[str] = []
    current_count = sum((1 for r in records if r.is_current))
    if current_count != 1:
        errors.append(f'Expected exactly 1 current record, found {current_count}')
    none_end_count = sum((1 for r in records if r.effective_end is None))
    if none_end_count != 1:
        errors.append(f'Expected exactly 1 record with effective_end=None, found {none_end_count}')
    for i, rec in enumerate(records):
        if rec.effective_end is not None:
            if rec.effective_end <= rec.effective_start:
                errors.append(f'Record {i}: effective_end ({rec.effective_end}) must be > effective_start ({rec.effective_start})')
        if i < len(records) - 1:
            next_rec = records[i + 1]
            if rec.effective_end != next_rec.effective_start:
                errors.append(f'Gap or overlap between record {i} and {i + 1}: record[{i}].effective_end={rec.effective_end} != record[{i + 1}].effective_start={next_rec.effective_start}')
    if errors:
        raise ValueError('Reconstructed history failed validation:\n' + '\n'.join(errors))
