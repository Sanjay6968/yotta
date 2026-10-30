import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
logger = logging.getLogger(__name__)
REQUIRED_COLUMNS = frozenset({'event_id', 'customer_id', 'customer_name', 'city', 'event_timestamp'})
TRACKED_ATTRIBUTES = ('customer_id', 'customer_name', 'city')
OPTIONAL_COLUMNS = frozenset({'source_sequence'})

@dataclass
class AcceptedEvent:
    event_id: str
    customer_id: str
    customer_name: str
    city: str
    event_timestamp: datetime
    source_file: str
    source_row_number: int
    payload_hash: str
    source_sequence: int | None

@dataclass
class RejectedEvent:
    source_file: str
    source_row_number: int
    raw_payload: dict
    rejection_reason: str

def check_schema(columns: list[str]) -> list[str]:
    present = set(columns)
    missing = sorted(REQUIRED_COLUMNS - present)
    return missing

def validate_row(row: dict[str, str], source_file: str, source_row_number: int) -> AcceptedEvent | RejectedEvent:
    problems: list[str] = []

    def _require_str(field_name: str) -> str:
        val = row.get(field_name, '').strip()
        if not val:
            problems.append(f'missing required field: {field_name!r}')
        return val
    event_id = _require_str('event_id')
    customer_id = _require_str('customer_id')
    customer_name = _require_str('customer_name')
    city = _require_str('city')
    event_timestamp: datetime | None = None
    raw_ts = row.get('event_timestamp', '').strip()
    if not raw_ts:
        problems.append("missing required field: 'event_timestamp'")
    else:
        parsed = _parse_timestamp(raw_ts)
        if parsed is None:
            problems.append(f"malformed timestamp: {raw_ts!r} — expected ISO 8601 with timezone, e.g. '2024-01-01T00:00:00+00:00'")
        elif parsed.tzinfo is None:
            problems.append(f'timezone-naive timestamp: {raw_ts!r} — all timestamps must include a UTC offset')
        else:
            event_timestamp = parsed.astimezone(timezone.utc)
    source_sequence: int | None = None
    raw_seq = row.get('source_sequence', '').strip()
    if raw_seq:
        try:
            source_sequence = int(raw_seq)
        except ValueError:
            problems.append(f'invalid source_sequence: {raw_seq!r} — must be an integer')
    if problems:
        return RejectedEvent(source_file=source_file, source_row_number=source_row_number, raw_payload=dict(row), rejection_reason='; '.join(problems))
    payload_hash = _compute_hash(customer_id, customer_name, city)
    return AcceptedEvent(event_id=event_id, customer_id=customer_id, customer_name=customer_name, city=city, event_timestamp=event_timestamp, source_file=source_file, source_row_number=source_row_number, payload_hash=payload_hash, source_sequence=source_sequence)

def _parse_timestamp(raw: str) -> datetime | None:
    normalised = raw.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        return None

def _compute_hash(customer_id: str, customer_name: str, city: str) -> str:
    content = '|'.join([customer_id.lower().strip(), customer_name.lower().strip(), city.lower().strip()])
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def compute_hash(customer_id: str, customer_name: str, city: str) -> str:
    return _compute_hash(customer_id, customer_name, city)
