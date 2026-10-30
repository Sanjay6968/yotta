-- ============================================================
-- ChronoLedger — Reconciliation Queries
-- Run these against the PostgreSQL DB to validate output
-- ============================================================

-- 1. PIPELINE RUN SUMMARY
--    Shows all runs, their status, and row counts
SELECT
    run_id,
    input_file,
    started_at,
    finished_at,
    status,
    input_count,
    accepted_count,
    rejected_count,
    dim_versions_written,
    ROUND(EXTRACT(EPOCH FROM (finished_at - started_at))::numeric, 3) AS duration_seconds
FROM pipeline_runs
ORDER BY started_at DESC;


-- 2. COMPLETE HISTORY FOR A SINGLE CUSTOMER
--    Change C1 to any customer_id you want to inspect
SELECT
    customer_id,
    name,
    email,
    city,
    plan,
    eff_start,
    eff_end,
    is_current,
    sk
FROM dim_customer
WHERE customer_id = 'C1'
ORDER BY eff_start;


-- 3. ALL CUSTOMERS WITH MORE THAN ONE SCD VERSION
--    Any customer here has had at least one attribute change
SELECT
    customer_id,
    COUNT(*) AS version_count,
    MIN(eff_start) AS first_seen,
    MAX(COALESCE(eff_end, CURRENT_DATE)) AS last_seen
FROM dim_customer
GROUP BY customer_id
HAVING COUNT(*) > 1
ORDER BY version_count DESC;


-- 4. CURRENT VERSION OF ALL CUSTOMERS
--    Exactly one row per customer (enforced by partial unique index)
SELECT
    customer_id,
    name,
    email,
    city,
    plan,
    eff_start AS current_since
FROM dim_customer
WHERE is_current = TRUE
ORDER BY customer_id;


-- 5. VERIFY NO OVERLAPPING INTERVALS PER CUSTOMER
--    Should return 0 rows. Any rows returned indicate a data integrity violation.
SELECT
    a.customer_id,
    a.eff_start AS a_start, a.eff_end AS a_end,
    b.eff_start AS b_start, b.eff_end AS b_end
FROM dim_customer a
JOIN dim_customer b
  ON a.customer_id = b.customer_id
 AND a.sk <> b.sk
 AND a.eff_start < COALESCE(b.eff_end, '9999-12-31')
 AND COALESCE(a.eff_end, '9999-12-31') > b.eff_start;


-- 6. VERIFY EXACTLY ONE CURRENT ROW PER CUSTOMER
--    Should return 0 rows. Any customer_id returned has a broken is_current flag.
SELECT customer_id, COUNT(*) AS current_count
FROM dim_customer
WHERE is_current = TRUE
GROUP BY customer_id
HAVING COUNT(*) <> 1;


-- 7. VERIFY VERSION CHAIN IS GAPLESS
--    For each customer, eff_end + 1 day should equal the next eff_start.
--    Returns gaps/overlaps. Should return 0 rows.
SELECT
    a.customer_id,
    a.eff_end,
    b.eff_start,
    b.eff_start - (a.eff_end + INTERVAL '1 day') AS gap
FROM dim_customer a
JOIN dim_customer b
  ON a.customer_id = b.customer_id
 AND b.eff_start = (
     SELECT MIN(c.eff_start)
     FROM dim_customer c
     WHERE c.customer_id = a.customer_id
       AND c.eff_start > a.eff_start
 )
WHERE a.eff_end IS NOT NULL
  AND b.eff_start <> a.eff_end + 1;


-- 8. SOURCE-TO-TARGET RECONCILIATION
--    For each run: input_count = accepted_count + rejected_count
--    Returns rows where the counts don't reconcile.
SELECT
    run_id,
    input_count,
    accepted_count,
    rejected_count,
    input_count - (accepted_count + rejected_count) AS discrepancy
FROM pipeline_runs
WHERE input_count <> (accepted_count + rejected_count);


-- 9. REJECTED RECORDS FROM THE LATEST RUN
--    Shows what was quarantined and why
SELECT
    r.run_id,
    r.source_row->>'customer_id' AS customer_id,
    r.reason,
    r.rejected_at
FROM rejected_records r
JOIN pipeline_runs p ON r.run_id = p.run_id::text
ORDER BY p.started_at DESC, r.rejected_at
LIMIT 50;


-- 10. TOTAL EVENT COUNT VS DIM VERSIONS
--     Accepted events >= dim versions (events include no-change duplicates)
SELECT
    p.run_id,
    p.accepted_count AS events_accepted,
    p.dim_versions_written AS dim_rows_written,
    p.accepted_count - p.dim_versions_written AS no_change_events
FROM pipeline_runs p
ORDER BY p.started_at DESC;


-- 11. FULL AUDIT: ALL VERSIONS FOR ALL CUSTOMERS (sorted by customer + time)
SELECT
    customer_id,
    eff_start,
    eff_end,
    is_current,
    name,
    email,
    city,
    plan
FROM dim_customer
ORDER BY customer_id, eff_start;
