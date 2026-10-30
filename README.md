# ChronoLedger

**An Auditable, Event-Driven SCD Type 2 Pipeline with Deterministic Historical Reconstruction**

Built for the YottaFlex.ai Associate AI Forward Deployed Engineer 72-hour coding challenge.

---

## What it does

ChronoLedger ingests customer event streams from CSV files and maintains a complete, auditable history of every customer's state over time using **Slowly Changing Dimensions Type 2 (SCD Type 2)**.

Key capabilities:

| Capability | Implementation |
|---|---|
| Immutable event ledger | `customer_events` table — never updated or deleted |
| Duplicate detection | SHA-256 hash comparison against the ledger |
| Conflict quarantine | Same `event_id`, different content → `rejected_records` |
| Late-arriving events | Full per-customer history reconstruction |
| Temporal integrity | Validated `[effective_start, effective_end)` intervals |
| Idempotent reruns | Re-processing the same file is safe (duplicates detected) |
| Audit trail | `pipeline_runs` tracks every metric of every execution |
| Reconciliation report | Generated after every run |

---

## Technology stack

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| Database | PostgreSQL 17 (Docker) |
| DB driver | psycopg2-binary |
| Testing | pytest |
| Hashing | hashlib (SHA-256) |
| Config | python-dotenv |

No Kafka, Spark, Airflow, cloud services, or frontend frameworks required.

---

## Architecture

```
Source CSV
    │
    ▼
Ingestion (ingestion.py)
    │   ├─ Schema validation (batch level)
    │   └─ Row validation (field level)
    │
    ├──────────────────────────────────┐
    ▼                                  ▼
Accepted events               Rejected records
    │                         (rejected_records table)
    ▼
Deduplication (deduplication.py)
    │   ├─ Exact duplicate   → skip (idempotent)
    │   ├─ Conflict          → quarantine (rejected_records)
    │   └─ New event         → insert into customer_events
    │
    ▼
Event Ledger (customer_events table)
    │
    ▼
Historical Reconstruction (reconstruction.py)
    │   ├─ Sort by (event_timestamp, source_sequence)
    │   ├─ Collapse consecutive identical states
    │   ├─ Derive [effective_start, effective_end) intervals
    │   └─ Validate temporal integrity
    │
    ▼
Transactional Publication (dimension_store.py)
    │   └─ Atomic delete-and-replace per customer
    │
    ▼
SCD Type 2 Dimension (dim_customer table)
    │
    ▼
Reconciliation & Audit Report (audit.py)
```

---

## Quick start

### Prerequisites

- Python 3.11+
- Docker Desktop
- Git

### Setup

```bash
git clone <repository-url>
cd chronoledger

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env if needed (defaults work with the Docker container below)

# Start PostgreSQL
docker run -d \
  --name chronoledger-pg \
  -e POSTGRES_DB=chronoledger \
  -e POSTGRES_USER=chronoledger_user \
  -e POSTGRES_PASSWORD=chronoledger_pass \
  -p 5432:5432 \
  postgres:17

# Wait for Postgres to be ready (~5 seconds), then initialise schema
python -m src.main --init-db
```

### Run the pipeline

```bash
# Process sample data
python -m src.main --run data/sample/sample_events.csv

# Process and generate audit report
python -m src.main --run data/sample/sample_events.csv --report

# Generate report only (from previous runs)
python -m src.main --report

# Show all options
python -m src.main --help
```

### Run tests

```bash
# All tests (119 total)
python -m pytest -v

# Unit tests only (no DB required)
python -m pytest tests/test_validation.py tests/test_deduplication.py tests/test_reconstruction.py -v

# Integration tests (requires Postgres)
python -m pytest tests/test_storage.py tests/test_event_store.py tests/test_dimension_store.py tests/test_pipeline.py -v
```

---

## Project structure

```
chronoledger/
├── src/
│   ├── config.py           # Typed config from environment variables
│   ├── storage.py          # DB connection, transaction context manager
│   ├── validation.py       # Pure row/schema validation, SHA-256 hashing
│   ├── ingestion.py        # CSV reader, orchestrates validation
│   ├── deduplication.py    # Pure event classification (new/dup/conflict)
│   ├── event_store.py      # DB reads/writes for customer_events + rejected_records
│   ├── reconstruction.py   # Deterministic SCD Type 2 history builder
│   ├── dimension_store.py  # DB reads/writes for dim_customer
│   ├── pipeline_store.py   # DB reads/writes for pipeline_runs
│   ├── pipeline.py         # Orchestrator — ties all modules together
│   ├── audit.py            # Reconciliation and audit report generator
│   └── main.py             # CLI entry point
├── sql/
│   └── schema.sql          # PostgreSQL DDL (4 tables, indexes, constraints)
├── data/
│   └── sample/
│       └── sample_events.csv  # 15 rows covering all scenarios
├── tests/
│   ├── test_config.py          #  7 tests
│   ├── test_validation.py      # 27 tests
│   ├── test_ingestion.py       # 13 tests
│   ├── test_deduplication.py   # 12 tests
│   ├── test_event_store.py     # 12 tests
│   ├── test_reconstruction.py  # 17 tests
│   ├── test_dimension_store.py # 15 tests
│   ├── test_pipeline.py        #  8 tests (end-to-end)
│   └── test_storage.py         #  8 tests
├── reports/                    # Generated audit reports
├── docs/
│   ├── assumptions.md          # Documented design assumptions (A1–A11)
│   ├── data_dictionary.md      # Full column-by-column reference
│   ├── design_tradeoffs.md     # Architecture decisions & trade-offs
│   ├── performance.md          # Benchmark results & optimization plan
│   ├── reconciliation_queries.sql  # SQL queries to validate output
│   └── llm_disclosure.md       # AI/LLM usage disclosure
├── scripts/
│   ├── generate_data.py        # Reproducible synthetic dataset generator
│   └── benchmark.py            # Pipeline throughput benchmark
├── .env.example
├── requirements.txt
└── pyproject.toml
```

---

## Data model

### customer_events (immutable event ledger)

| Column | Type | Notes |
|---|---|---|
| event_id | TEXT PK | Stable source identifier |
| customer_id | TEXT | Business key |
| customer_name | TEXT | Tracked SCD attribute |
| city | TEXT | Tracked SCD attribute |
| event_timestamp | TIMESTAMPTZ | **Business time** — when the fact became true |
| ingested_at | TIMESTAMPTZ | **Transaction time** — when we received it |
| payload_hash | TEXT | SHA-256 of (customer_id, customer_name, city) |
| source_sequence | INTEGER | Tie-breaker for same-timestamp events |
| run_id | TEXT | Which pipeline run inserted this row |

### dim_customer (SCD Type 2 dimension)

| Column | Type | Notes |
|---|---|---|
| customer_sk | SERIAL PK | Surrogate key |
| customer_id | TEXT | Business key |
| customer_name | TEXT | State at this version |
| city | TEXT | State at this version |
| effective_start | TIMESTAMPTZ | Inclusive start of validity |
| effective_end | TIMESTAMPTZ | Exclusive end (NULL = current) |
| is_current | BOOLEAN | Convenience flag |
| record_hash | TEXT | SHA-256 for change detection |
| run_id | TEXT | Which run created this version |

**Interval semantics:** `[effective_start, effective_end)` — start is inclusive, end is exclusive.

### rejected_records

All records that failed validation or conflict detection, with the original payload preserved as JSONB.

### pipeline_runs

One row per pipeline execution with full operational metrics.

---

## Key design decisions

### 1. Targeted per-customer reconstruction (not incremental patching)

When a new or late-arriving event affects a customer, we **delete all their dimension rows and rebuild from the full event ledger**. This is always correct, even for late-arriving events that split or restructure existing intervals.

Incremental patching (UPDATE current row, INSERT one new row) is wrong for late arrivals.

### 2. Classify before write

We look up all incoming `event_id`s in one batch query before writing anything. This avoids catching Postgres constraint violations one row at a time and gives us clean, testable classification logic.

### 3. Pure functions + thin DB layer

`validation.py`, `deduplication.py`, and `reconstruction.py` are pure Python — no DB calls, fully unit-testable without Docker.

DB calls are isolated to `*_store.py` modules.

### 4. Atomic transactions

All DB writes in a single pipeline run happen inside one `BEGIN`/`COMMIT` block. If anything fails, the entire run is rolled back. The `pipeline_runs` row is written in autocommit mode so it always persists (even on failure).

---

## Research-informed design concepts

| Concept | Implementation |
|---|---|
| Valid time vs transaction time | `event_timestamp` (business time) vs `ingested_at` (transaction time) |
| Deterministic reconstruction | Pure function produces same output for same input regardless of event arrival order |
| Event deduplication | SHA-256 hash comparison; payload-identical re-arrivals are idempotent |
| Temporal integrity constraints | `_validate_history()` checks contiguity and `effective_end > effective_start` before any DB write |
| Idempotency | Re-running the same file returns duplicate counts, no duplicate DB rows |
| Transactional publication | Atomic delete-and-replace per customer; partial writes are impossible |

---

## Test results

```
119 passed in 2.77s
```

| Test file | Tests | Type |
|---|---|---|
| test_config.py | 7 | Unit |
| test_validation.py | 27 | Unit |
| test_ingestion.py | 13 | Unit |
| test_deduplication.py | 12 | Unit |
| test_reconstruction.py | 17 | Unit |
| test_event_store.py | 12 | Integration (Postgres) |
| test_dimension_store.py | 15 | Integration (Postgres) |
| test_storage.py | 8 | Integration (Postgres) |
| test_pipeline.py | 8 | End-to-end (Postgres) |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| DB_HOST | localhost | PostgreSQL host |
| DB_PORT | 5432 | PostgreSQL port |
| DB_NAME | chronoledger | Database name |
| DB_USER | chronoledger_user | Database user |
| DB_PASSWORD | chronoledger_pass | Database password |
| LOG_LEVEL | INFO | Logging verbosity |
| PIPELINE_SCHEMA | public | PostgreSQL schema |

---

## Synthetic data generation

ChronoLedger includes a reproducible dataset generator with a fixed random seed (42):

```bash
# Small dataset (1,000 rows, 100 customers)
python scripts/generate_data.py --rows 1000 --output data/generated/events.csv

# Large dataset (100,000 rows, 10,000 customers)
python scripts/generate_data.py --rows 100000 --output data/generated/large_events.csv

# Custom seed
python scripts/generate_data.py --rows 5000 --seed 99 --output data/generated/custom.csv
```

Generated data includes: normal updates, exact duplicates, malformed rows, late-arriving events, and same-timestamp conflicts.

### Benchmark

```bash
# Run pipeline + measure throughput
python scripts/benchmark.py --input data/generated/medium_events.csv
```

See [`docs/performance.md`](docs/performance.md) for benchmark results and optimization analysis.

---

## Documentation

| Document | Description |
|---|---|
| [`docs/data_dictionary.md`](docs/data_dictionary.md) | Full column-by-column reference for all tables |
| [`docs/design_tradeoffs.md`](docs/design_tradeoffs.md) | Key architecture decisions and trade-offs |
| [`docs/assumptions.md`](docs/assumptions.md) | Documented assumptions (A1–A11) |
| [`docs/performance.md`](docs/performance.md) | Benchmark results and optimization plan |
| [`docs/reconciliation_queries.sql`](docs/reconciliation_queries.sql) | SQL queries to validate output correctness |
| [`docs/llm_disclosure.md`](docs/llm_disclosure.md) | AI/LLM usage disclosure |

---

## Known limitations

- Single-threaded reconstruction — one customer at a time (see `docs/performance.md` for fix)
- PostgreSQL only — no SQLite adapter for lightweight CI
- No soft-delete support (deleted customers remain `is_current = TRUE`)
- `event_timestamp` granularity is seconds; sub-second conflicts rely on `source_sequence`

---

## Possible next steps

1. Batch customer lookups with `ANY()` to reduce N DB round-trips to 1
2. Parallelize per-customer reconstruction with `ThreadPoolExecutor`
3. Add streaming ingestion via Kafka consumer
4. Model `dim_customer` as a dbt incremental model
5. Add REST API: `GET /customers/{id}/history`

---

## Python version

Developed and tested on **Python 3.14.6** and **PostgreSQL 17**.
