import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from src.validation import AcceptedEvent, RejectedEvent, check_schema, validate_row
logger = logging.getLogger(__name__)

@dataclass
class IngestionResult:
    source_file: str
    accepted: list[AcceptedEvent] = field(default_factory=list)
    rejected: list[RejectedEvent] = field(default_factory=list)
    schema_error: str = ''
    input_count: int = 0

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

def ingest_file(file_path: str | Path) -> IngestionResult:
    file_path = Path(file_path)
    source_file = str(file_path)
    result = IngestionResult(source_file=source_file)
    logger.info('Ingesting file: %s', source_file)
    with open(file_path, encoding='utf-8', newline='') as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames or []
        missing = check_schema(list(columns))
        if missing:
            result.schema_error = f'Schema mismatch: missing required columns: {missing}. Found columns: {list(columns)}. Entire batch rejected.'
            logger.error('Batch rejected — %s', result.schema_error)
            return result
        logger.debug('Schema OK. Columns: %s', list(columns))
        for row_index, raw_row in enumerate(reader, start=1):
            result.input_count += 1
            validated = validate_row(row=dict(raw_row), source_file=source_file, source_row_number=row_index)
            if isinstance(validated, AcceptedEvent):
                result.accepted.append(validated)
                logger.debug('Row %d accepted: event_id=%s customer_id=%s', row_index, validated.event_id, validated.customer_id)
            else:
                result.rejected.append(validated)
                logger.warning('Row %d rejected: %s | payload=%s', row_index, validated.rejection_reason, validated.raw_payload)
    logger.info('Ingestion complete: %d input, %d accepted, %d rejected', result.input_count, result.accepted_count, result.rejected_count)
    return result
