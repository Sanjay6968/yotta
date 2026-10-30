# Data Dictionary — ChronoLedger

All tables use `snake_case` naming. Timestamps are ISO-8601 (UTC). UUIDs are generated via `gen_random_uuid()` or Python `uuid4()`.

---

## Source Schema

### Input CSV (`data/sample/sample_events.csv`, generated CSVs)

| Column | Type | Nullable | Description |
|---|---|---|---|
| `event_id` | STRING | No | Stable source identifier for this event (e.g. `E001`). Used for exact-duplicate detection. |
| `customer_id` | STRING | No | Business key; stable across all source events (e.g. `C1`, `C000001`) |
| `customer_name` | STRING | No | Customer full name |
| `city` | STRING | No | Customer city of residence |
| `event_timestamp` | ISO-8601 STRING | No | The datetime this record became effective in the source system (must include timezone, e.g. `2024-01-01T00:00:00+00:00`) |
| `source_sequence` | INTEGER | No | Tie-breaker within the same `customer_id + event_timestamp`; lower = earlier |

---

## Target Schema (PostgreSQL)

### `pipeline_runs`

Tracks each pipeline invocation for auditing and idempotency.

| Column | Type | Nullable | PK/FK | Description |
|---|---|---|---|---|
| `run_id` | UUID | No | PK | Auto-generated unique run identifier |
| `input_file` | TEXT | Yes | — | Source file path or label |
| `started_at` | TIMESTAMPTZ | No | — | Pipeline start time (UTC) |
| `finished_at` | TIMESTAMPTZ | Yes | — | Pipeline end time; NULL if still running |
| `status` | TEXT | No | — | `running`, `success`, or `failed` |
| `input_count` | INTEGER | Yes | — | Total rows read from source |
| `accepted_count` | INTEGER | Yes | — | Rows that passed validation |
| `rejected_count` | INTEGER | Yes | — | Rows that failed validation |
| `dim_versions_written` | INTEGER | Yes | — | SCD rows inserted in `dim_customer` |
| `error_message` | TEXT | Yes | — | Set on failure; NULL on success |

---

### `ledger_events` (a.k.a. `customer_events`)

Append-only event store. Every accepted source row lands here exactly once (idempotent on `event_id` — duplicate events are detected and skipped).

| Column | Type | Nullable | PK/FK | Description |
|---|---|---|---|---|
| `event_id` | TEXT | No | PK | Source event identifier |
| `customer_id` | TEXT | No | — | Business key |
| `customer_name` | TEXT | No | — | Customer name at event time |
| `city` | TEXT | No | — | Customer city at event time |
| `event_timestamp` | TIMESTAMPTZ | No | — | Source business timestamp (when fact became true) |
| `ingested_at` | TIMESTAMPTZ | No | — | Wall-clock time of ingestion (transaction time) |
| `payload_hash` | TEXT | No | — | SHA-256 of tracked attributes; used for conflict detection |
| `source_sequence` | INTEGER | Yes | — | Source tie-breaker for same-timestamp events |
| `run_id` | TEXT | No | — | Pipeline run that inserted this row |

---

### `dim_customer`

SCD Type 2 dimension table. Each row represents one version of a customer's attributes.

| Column | Type | Nullable | PK/FK | Description | Derivation |
|---|---|---|---|---|---|
| `customer_sk` | SERIAL | No | PK | Surrogate key | Auto-increment |
| `customer_id` | TEXT | No | — | Business key | From source |
| `customer_name` | TEXT | No | — | Customer name for this version | From source |
| `city` | TEXT | No | — | Customer city for this version | From source |
| `effective_start` | TIMESTAMPTZ | No | — | Inclusive start of validity | Equals `event_timestamp` of the event that opened this version |
| `effective_end` | TIMESTAMPTZ | Yes | — | Exclusive end of validity; NULL = current row | Set when a newer version closes this row |
| `is_current` | BOOLEAN | No | — | `TRUE` for the open version of each customer | Maintained by reconstruction |
| `record_hash` | TEXT | No | — | SHA-256 of tracked attributes; mirrors event's `payload_hash` | From source event |
| `run_id` | TEXT | No | — | Run that last wrote this row | Set on INSERT |

> **SCD Type 2 mechanics:** When a source event changes any tracked attribute (`customer_name`, `city`), the full history for that customer is rebuilt: existing `dim_customer` rows for that customer are deleted and re-inserted from the event ledger with correct `[effective_start, effective_end)` intervals.

> **Interval semantics:** `[effective_start, effective_end)` — start is inclusive, end is exclusive. The current row has `effective_end = NULL`.

---

### `rejected_records`

Quarantine table for rows that fail validation or conflict detection. Keeps source data traceable.

| Column | Type | Nullable | PK/FK | Description |
|---|---|---|---|---|
| `id` | SERIAL | No | PK | Surrogate key |
| `run_id` | TEXT | No | — | Pipeline run that rejected this row |
| `source_row_number` | INTEGER | Yes | — | Row number in the source file |
| `raw_payload` | JSONB | No | — | Original row data as JSON |
| `rejection_reason` | TEXT | No | — | Human-readable rejection reason |
| `rejected_at` | TIMESTAMPTZ | No | — | Wall-clock time of rejection |

---

## Naming Conventions

| Convention | Rule |
|---|---|
| Tables | `snake_case`, singular or plural noun |
| Columns | `snake_case` |
| Surrogate keys | Auto-increment integer named `customer_sk` (dim), `id` (audit tables), or `event_id` (ledger) |
| Business keys | Named `customer_id`; stable across all events |
| Timestamps | All stored as `TIMESTAMPTZ` (UTC); displayed as ISO-8601 |
| Boolean flags | Lowercase `true`/`false`; column named `is_<state>` |
| Run IDs | `UUID` in `pipeline_runs`; stored as `TEXT` in child tables (no FK constraint — see `docs/assumptions.md` A11) |
| Hashes | SHA-256 hex string; column named `payload_hash` (events) or `record_hash` (dim) |
