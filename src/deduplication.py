from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import NamedTuple
from src.validation import AcceptedEvent, RejectedEvent
logger = logging.getLogger(__name__)

class LedgerEntry(NamedTuple):
    event_id: str
    payload_hash: str

@dataclass(frozen=True)
class DeduplicationResult:
    new_events: list[AcceptedEvent] = field(default_factory=list)
    duplicates: list[AcceptedEvent] = field(default_factory=list)
    conflicts: list[RejectedEvent] = field(default_factory=list)

    @property
    def new_count(self) -> int:
        return len(self.new_events)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)

def classify_events(incoming: list[AcceptedEvent], ledger: dict[str, str], source_file: str='', run_id: str='') -> DeduplicationResult:
    new_events: list[AcceptedEvent] = []
    duplicates: list[AcceptedEvent] = []
    conflicts: list[RejectedEvent] = []
    working_ledger: dict[str, str] = dict(ledger)
    for event in incoming:
        eid = event.event_id
        if eid not in working_ledger:
            new_events.append(event)
            working_ledger[eid] = event.payload_hash
            logger.debug('NEW event_id=%s', eid)
        elif working_ledger[eid] == event.payload_hash:
            duplicates.append(event)
            logger.debug('DUPLICATE event_id=%s', eid)
        else:
            existing_hash = working_ledger[eid]
            reason = f"CONFLICT: event_id '{eid}' already exists in the ledger with payload_hash '{existing_hash}' but arrived again with payload_hash '{event.payload_hash}'. Two contradictory versions of the same event_id cannot both be correct. The new arrival is quarantined."
            rejected = RejectedEvent(source_file=source_file or event.source_file, source_row_number=event.source_row_number, raw_payload=_event_to_raw_payload(event), rejection_reason=reason)
            conflicts.append(rejected)
            logger.warning('CONFLICT event_id=%s', eid)
    logger.info('Deduplication: new=%d duplicates=%d conflicts=%d', len(new_events), len(duplicates), len(conflicts))
    return DeduplicationResult(new_events=new_events, duplicates=duplicates, conflicts=conflicts)

def _event_to_raw_payload(event: AcceptedEvent) -> dict:
    return {'event_id': event.event_id, 'customer_id': event.customer_id, 'customer_name': event.customer_name, 'city': event.city, 'event_timestamp': event.event_timestamp.isoformat(), 'payload_hash': event.payload_hash, 'source_sequence': event.source_sequence}
