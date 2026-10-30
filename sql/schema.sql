CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id                  UUID        PRIMARY KEY,
    input_file              TEXT        NOT NULL DEFAULT '',
    started_at              TIMESTAMPTZ NOT NULL,
    finished_at             TIMESTAMPTZ,
    status                  TEXT        NOT NULL
                                CHECK (status IN ('running', 'success', 'failed')),
    input_count             INTEGER,
    accepted_count          INTEGER,
    rejected_count          INTEGER,
    duplicate_count         INTEGER,
    conflict_count          INTEGER,
    event_insert_count      INTEGER,
    dimension_insert_count  INTEGER,
    dimension_update_count  INTEGER,
    late_event_count        INTEGER,
    processing_duration_ms  INTEGER,
    error_message           TEXT
);
COMMENT ON TABLE pipeline_runs IS
    'One row per pipeline execution. Counts are mutually exclusive: '
    'input_count = accepted_count + rejected_count. '
    'event_insert_count <= accepted_count because exact duplicates are skipped. '
    'dimension_insert_count <= event_insert_count because unchanged states produce no new version.';
CREATE TABLE IF NOT EXISTS customer_events (
    event_id            TEXT        PRIMARY KEY,
    customer_id         TEXT        NOT NULL,
    customer_name       TEXT        NOT NULL,
    city                TEXT        NOT NULL,
    event_timestamp     TIMESTAMPTZ NOT NULL,
    source_file         TEXT        NOT NULL,
    source_row_number   INTEGER,
    ingested_at         TIMESTAMPTZ NOT NULL,
    payload_hash        TEXT        NOT NULL,
    source_sequence     INTEGER,
    run_id              TEXT        NOT NULL DEFAULT 'bootstrap'
);
CREATE INDEX IF NOT EXISTS idx_customer_events_customer_time
    ON customer_events (customer_id, event_timestamp, source_sequence NULLS LAST);
COMMENT ON TABLE customer_events IS
    'Immutable event ledger. One row per accepted source event. '
    'Never updated or deleted after insert. '
    'event_timestamp = business time (when the fact became true). '
    'ingested_at = transaction time (when we received it).';
CREATE TABLE IF NOT EXISTS dim_customer (
    customer_sk     SERIAL      PRIMARY KEY,
    customer_id     TEXT        NOT NULL,
    customer_name   TEXT        NOT NULL,
    city            TEXT        NOT NULL,
    effective_start TIMESTAMPTZ NOT NULL,
    effective_end   TIMESTAMPTZ,
    is_current      BOOLEAN     NOT NULL,
    record_hash     TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    run_id          TEXT        NOT NULL,
    CONSTRAINT chk_effective_dates CHECK (
        effective_end IS NULL OR effective_end > effective_start
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uidx_dim_customer_one_current
    ON dim_customer (customer_id)
    WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS idx_dim_customer_history
    ON dim_customer (customer_id, effective_start);
COMMENT ON TABLE dim_customer IS
    'SCD Type 2 customer dimension. '
    'Interval semantics: [effective_start, effective_end). '
    'effective_end = NULL for the current active version. '
    'Partial unique index ensures at most one current version per customer_id.';
CREATE TABLE IF NOT EXISTS rejected_records (
    reject_id           SERIAL      PRIMARY KEY,
    run_id              TEXT        NOT NULL,
    source_file         TEXT        NOT NULL,
    source_row_number   INTEGER,
    raw_payload         JSONB       NOT NULL,
    rejection_reason    TEXT        NOT NULL,
    rejected_at         TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE rejected_records IS
    'Quarantine for rejected and conflicting records. '
    'raw_payload preserves the original input for audit and reprocessing. '
    'rejection_reason is human-readable and suitable for operational reports.';
