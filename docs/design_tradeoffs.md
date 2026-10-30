# Design Choices & Trade-offs — ChronoLedger

## Architecture Overview

ChronoLedger implements a **three-layer pipeline**:

```
CSV Input → Validation/Quarantine → Event Store (ledger_events) → SCD Reconstruction → dim_customer
```

The event store acts as a permanent, append-only log. The SCD dimension is derived from it at run time. This means the dimension can be fully rebuilt from scratch by replaying the event store — a strong idempotency guarantee.

---

## Key Design Decisions

### 1. Targeted per-customer reconstruction vs. incremental patching

**Chosen:** For each pipeline run, collect all affected `customer_id`s, then delete-and-rebuild their full SCD chains from the event store.

**Alternative:** Detect only the *new* events and apply incremental `UPDATE + INSERT` SQL.

**Rationale:** Incremental patching is faster for large tables but introduces edge cases: late-arriving events that land *before* an existing version require retroactive interval adjustment, which is error-prone. Targeted rebuild is O(events per customer) — cheap given typical customer cardinalities — and is provably correct because the full event history is always replayed. The event store is the source of truth; the dimension is always a pure derived view.

**Trade-off:** At 100k+ events across 10k+ customers, rebuilding all customers in a single run adds latency compared to a narrow incremental approach. The optimization path (see `docs/performance.md`) is to batch `customer_id` lookups with `ANY()` and parallelize per-customer reconstruction.

---

### 2. `run_id` stored as TEXT in child tables (no FK to `pipeline_runs`)

**Chosen:** `ledger_events.run_id` and `rejected_records.run_id` are `TEXT`, not `UUID REFERENCES pipeline_runs`.

**Alternative:** Foreign-key constraint `UUID REFERENCES pipeline_runs(run_id)`.

**Rationale:** The FK constraint requires the `pipeline_runs` row to be committed before child rows can be inserted. In a multi-transaction pipeline, the run row is open (status = `running`) during child inserts, which works — but adds coupling. Storing `run_id` as `TEXT` also allows test fixtures to use simple string IDs without registering a real `pipeline_runs` row, keeping unit tests fast and decoupled. See `docs/assumptions.md` A11.

**Trade-off:** No DB-enforced referential integrity between run and its events. A `CHECK` constraint or periodic audit query (reconciliation_queries.sql #10) compensates.

---

### 3. Pure classification layer for deduplication (`deduplication.py`)

**Chosen:** `deduplication.py` classifies events as `new`, `duplicate`, or `superseded` using only in-memory data — no database calls.

**Alternative:** Query the DB inside the classifier to detect true duplicates against existing event store rows.

**Rationale:** Separation of concerns. The classifier is pure Python — trivially unit-testable without a DB. The event store enforces uniqueness at the DB level via the `UNIQUE (customer_id, effective_date, source_sequence)` constraint. The classification layer is an optimization (avoids unnecessary DB round-trips for within-batch duplicates) and a UX improvement (rejects with a human-readable reason before the DB attempt).

**Trade-off:** If the same event arrives in *different batches*, the classifier sees it as `new` (no history), but the DB unique constraint rejects it gracefully. This is the correct behavior — the event store is idempotent.

---

### 4. Same-timestamp conflict resolution: "supersede" rule

**Chosen:** When two events share the same `customer_id + effective_date` but have *different content* and different `source_sequence`, the lower-sequence event is marked `superseded` (eff_end = eff_start, is_current = FALSE but still stored) and the higher-sequence event opens the live version.

**Alternative:** Reject all but the first-seen event; or reject all ambiguous events.

**Rationale:** The source system may emit correction events for the same effective date (e.g., an initial record followed by a corrected email). Keeping both events in the ledger preserves the full audit trail. The "supersede" rule avoids zero-duration intervals (eff_start = eff_end would be confusing) by recording the correction as an instantaneous state that was immediately replaced.

**Trade-off:** The dimension may have a version row with `eff_start = eff_end` for superseded states, which surprises some BI tools. This is documented in `docs/assumptions.md` A7.

---

### 5. No foreign-key relationship between `dim_customer` and `ledger_events`

**Chosen:** `dim_customer` rows do not link back to the `ledger_events` rows that created them.

**Alternative:** Add `event_id UUID REFERENCES ledger_events` to `dim_customer`.

**Rationale:** The reconstruction step rebuilds the dimension from all events for a customer; a single dim version may be caused by one event but is influenced by the ordering of all events. Linking to a single event_id would be misleading. Lineage is traceable via `run_id` and the event store query.

---

## Known Limitations

| Limitation | Impact | Possible Fix |
|---|---|---|
| Single-threaded reconstruction | Slow for >500k events with many distinct customers | Parallelize with `concurrent.futures.ThreadPoolExecutor` per customer shard |
| No incremental CDC support | Full reload needed if source emits only changes without full snapshots | Add a `change_type` field (`I/U/D`) and handle deletes as SCD closures |
| SQLite not supported | Tests require PostgreSQL Docker container | Add an optional SQLite adapter for lightweight CI |
| No soft-delete support | Deleted customers remain as `is_current = TRUE` forever | Handle `DELETE` events by setting `eff_end = delete_date, is_current = FALSE` |
| `eff_end` uses `DATE`, not `TIMESTAMPTZ` | Two changes on the same calendar date collide (handled by `source_sequence`) | Use `TIMESTAMPTZ` for sub-day granularity if source timestamps are reliable |

---

## Possible Next Steps

1. **REST API layer** — Expose `GET /customers/{id}/history` to serve SCD history directly from `dim_customer`.
2. **Streaming ingestion** — Replace file-based CSV with Kafka consumer; the event store design is already append-only and compatible.
3. **dbt integration** — Model `dim_customer` as a dbt incremental model using the `unique_key` strategy.
4. **Partitioning** — Partition `ledger_events` by `effective_date` month for query performance at scale.
5. **Multi-entity support** — Generalize the pipeline to handle `dim_product`, `dim_employee`, etc. with a shared event store schema.
