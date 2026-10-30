# ChronoLedger — Design Assumptions

This document records every non-obvious design assumption made during implementation.
Each assumption has an ID (A1, A2, …) so it can be referenced from code comments and tests.

---

## A1 — Complete state events

**Assumption:** Each source event contains the **complete customer state** as of `event_timestamp`.

For example, an event `{customer_id: C1, customer_name: Alice, city: Hyderabad, event_timestamp: 2024-01-01}` means that on 2024-01-01, Alice's complete known state was `{name: Alice, city: Hyderabad}`.

**Why:** This simplifies reconstruction — we do not need to merge partial updates.

**If violated:** If the source sends partial updates (e.g., "city changed to Bangalore, name unchanged"), the pipeline would need a fold/merge step to reconstruct the full state from a series of deltas. This is not implemented.

---

## A2 — event_id is a stable source identifier

**Assumption:** `event_id` is assigned by the source system and is stable. The same business event always arrives with the same `event_id`.

**Why:** We use `event_id` as the primary key of the event ledger. A stable identifier allows us to detect true duplicates vs. conflicting versions of the same event.

**If violated:** If `event_id`s are not stable (e.g., the source regenerates them on retry), we cannot perform meaningful deduplication. `payload_hash` alone would be needed.

---

## A3 — event_timestamp is business time, not processing time

**Assumption:** `event_timestamp` represents **when the business fact became true in the real world**, not when the source system generated the event.

**Why:** SCD effective dates must reflect real-world validity, not processing order. An event timestamped 2024-02-01 that arrives on 2024-05-01 (late) must be placed at February in the history, not May.

---

## A4 — Timezone-aware timestamps required

**Assumption:** All `event_timestamp` values must be timezone-aware. Naive (no timezone) timestamps are rejected.

**Why:** Naive timestamps are ambiguous. If a timestamp is `2024-01-01T00:00:00` without a timezone, we cannot determine whether it is UTC, IST, or something else. Silently assuming UTC would be wrong and could cause incorrect interval ordering.

---

## A5 — Tracked attributes

**Assumption:** The tracked SCD attributes are `customer_name` and `city` (alongside `customer_id` which is the business key). A change in any tracked attribute creates a new dimension version. `event_id`, timestamps, and operational fields are NOT tracked.

---

## A6 — Case-insensitive, whitespace-normalised hashing

**Assumption:** Tracked attributes are normalised to lowercase and stripped of leading/trailing whitespace before hashing.

**Why:** `"Hyderabad"` and `"hyderabad"` represent the same city. Without normalisation, a formatting difference in the source would create a spurious dimension version.

**Risk:** If the source intentionally sends mixed-case values that are semantically different (unlikely for city names), this normalisation could incorrectly collapse them.

---

## A7 — Same-timestamp tie-breaking by source_sequence

**Assumption:** If two events for the same `customer_id` share the exact same `event_timestamp`, the event with the **higher `source_sequence`** is considered more recent and authoritative.

If `source_sequence` is not provided for both events, the order is ambiguous.

**Behaviour when ambiguous:** The sort is stable (Python's `sorted()` is stable), so the order of arrival in the batch determines the winner. This is documented here so it is explicit, not accidental.

**Special case:** Two events at the same timestamp with different content produce a zero-duration interval, which is invalid. We resolve this by **superseding** — only the last event (by source_sequence) survives. See `reconstruction.py` Step 3, Rule B.

---

## A8 — Idempotent reruns via event_id + payload_hash

**Assumption:** Re-processing the same source file is safe. An event is classified as an exact duplicate if and only if it has the same `event_id` AND the same `payload_hash` as a row already in the ledger.

**Why:** Re-runs must not produce duplicate dimension versions. The event ledger's primary key on `event_id` provides the DB-level guarantee; the deduplication layer provides the application-level guarantee.

---

## A9 — Conflict policy: quarantine, do not overwrite

**Assumption:** If the same `event_id` arrives with different content (different `payload_hash`), this is a **conflict** — the source sent two contradictory versions of the same event. We quarantine the new arrival in `rejected_records` with a detailed reason.

**We do NOT silently overwrite** the existing ledger entry. The first version stands until a manual review and correction process runs.

**Alternative:** Some systems use "last write wins". We explicitly reject this because it destroys the audit trail.

---

## A10 — Targeted per-customer reconstruction

**Assumption:** When a new or late event arrives for a customer, we rebuild their **entire dimension history** from the full event ledger (delete all rows, insert the reconstructed set).

**Why correct:** A late-arriving event can restructure all intervals, not just the latest one. Incremental patching would be wrong.

**Performance:** For a customer with N historical versions, this costs N deletes + N inserts per affected customer per run. For typical SCD data (5–50 versions per customer), this is fast. At very large scale (10k+ versions per customer), batched incremental patching would be needed — optimise only after measuring.

---

## A11 — run_id type: TEXT not UUID

**Assumption:** `run_id` is stored as `TEXT` in `customer_events` and `rejected_records` (not as the native `UUID` type), while `pipeline_runs.run_id` is the authoritative `UUID PRIMARY KEY`.

**Why:** This allows test code to use human-readable run IDs (`"test-run-dimstore"`) without casting, and allows the `customer_events.run_id` to hold the special value `'bootstrap'` for rows inserted during schema initialisation. The FK-style relationship is enforced at the application layer, not with a database FOREIGN KEY constraint.
