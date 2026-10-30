# Performance Measurement — ChronoLedger

## Benchmark Results

### Test Environment

| Item | Value |
|---|---|
| OS | Windows 11 |
| Python | 3.14.6 |
| Database | PostgreSQL 17 (Docker `chronoledger-pg`, localhost:5432) |
| Hardware | ASUS laptop, local Docker container |

---

### Run: 1,000-row generated dataset (100 customers)

```
Input file  : data/generated/medium_events.csv
Input rows  : 1,000
Customers   : 100
Accepted    : 903
Rejected    : 97 (malformed / invalid)
Events ins. : 776
Dup skipped : 127
Dim versions: 661
Duration    : 3.755s
Throughput  : ~266 rows/sec
```

**Command:**
```bash
python scripts/benchmark.py --input data/generated/medium_events.csv
```

---

### Dataset Generator Stats (100k row run)

```
Input rows  : 100,000
Customers   : 10,000
~Malformed  : ~9,400 rows (9.4%)
Seed        : 42
Generation time: < 8s
```

**Command:**
```bash
python scripts/generate_data.py --rows 100000 --output data/generated/large_events.csv
```

---

## Profiling Analysis

### Where time is spent (1,000-row run, ~3.75s total)

| Stage | Estimated % | Notes |
|---|---|---|
| DB round-trips (event fetch) | ~60% | One `SELECT` per customer to fetch existing events |
| SCD reconstruction (in-memory) | ~15% | Sorting + interval assignment per customer |
| DB writes (event insert + dim upsert) | ~20% | Bulk inserts via `executemany` |
| Validation + parsing | ~5% | Pure Python, negligible |

The dominant cost is **N separate `SELECT` queries** — one per distinct customer in the batch.

---

## Identified Bottleneck & Optimization

### Current: N queries (one per customer)

```python
# event_store.py — current approach
for customer_id in affected_customers:
    events = fetch_ledger_entries(customer_id)   # 1 SELECT per customer
```

With 100 customers this is 100 round-trips. With 10,000 customers it's 10,000 round-trips.

### Proposed Optimization: Single `ANY()` batch query

```sql
-- Replace N individual SELECTs with one batched query:
SELECT * FROM ledger_events
WHERE customer_id = ANY(%(customer_ids)s)
ORDER BY customer_id, event_timestamp, source_sequence;
```

```python
# Fetch all affected customers in one query, then group in Python
rows = fetch_ledger_entries_batch(list(affected_customers))
events_by_customer = {}
for row in rows:
    events_by_customer.setdefault(row["customer_id"], []).append(row)
```

**Expected speedup:** For 10,000 customers, reducing 10,000 SELECT round-trips to 1 would cut the DB fetch phase from ~minutes to ~seconds (linear → constant in query count).

### Secondary Optimization: Parallel per-customer reconstruction

Each customer's SCD reconstruction is independent. Using `concurrent.futures.ThreadPoolExecutor`:

```python
with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
    futures = {pool.submit(reconstruct_customer, cid, events): cid
               for cid, events in events_by_customer.items()}
```

This would reduce wall time proportionally to CPU core count for large customer sets.

---

## Scaling Estimate

| Rows | Customers | Estimated time (current) | Estimated time (optimized) |
|---|---|---|---|
| 1,000 | 100 | ~3.8s | ~1.5s |
| 10,000 | 1,000 | ~35s | ~5s |
| 100,000 | 10,000 | ~350s (~6 min) | ~20s |

> **Note:** Estimates extrapolated from 1k benchmark. Actual times depend on hardware and DB load.

---

## Reproducibility

To reproduce the benchmark:

```bash
# 1. Start Docker
docker start chronoledger-pg

# 2. Generate data (deterministic, seed=42)
python scripts/generate_data.py --rows 1000 --output data/generated/medium_events.csv

# 3. Run benchmark
python scripts/benchmark.py --input data/generated/medium_events.csv
```
