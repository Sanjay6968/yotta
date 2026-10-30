# AI / LLM Usage Disclosure

## Summary

This project was developed with the assistance of an AI coding assistant (Google Antigravity / Gemini). The AI was used as a **pair programming tool** — it generated code drafts, wrote documentation, and suggested architectural patterns. All critical decisions were reviewed and validated by the candidate.

---

## What the AI Did

| Area | AI Contribution |
|---|---|
| Initial schema design | Drafted `sql/schema.sql`; candidate reviewed and approved constraints, types, and indexes |
| Core pipeline modules | Drafted `src/pipeline.py`, `src/reconstruction.py`, `src/validation.py` etc.; candidate reviewed logic |
| Test suite | Generated test stubs; candidate validated test coverage, edge cases, and actual results |
| Documentation | Drafted `README.md`, `docs/data_dictionary.md`, `docs/design_tradeoffs.md`; candidate approved content |
| SQL reconciliation queries | Drafted `docs/reconciliation_queries.sql`; candidate verified correctness against live DB |
| Data generator | Drafted `scripts/generate_data.py`; candidate configured seed and distribution parameters |
| Debugging | AI suggested fixes for schema type mismatches (`run_id TEXT` vs `UUID`), missing columns, and Windows `&&` chaining issues |

---

## What the Candidate Personally Validated

- Ran all 119 tests locally and verified they pass: `python -m pytest -v`
- Executed the pipeline on sample data and queried the DB to confirm SCD versions are correct (C1 has 3 versions: Hyderabad → Chennai → Bangalore)
- Verified temporal integrity: no overlapping intervals, exactly one `is_current = TRUE` per customer
- Reviewed the SCD reconstruction logic (`src/reconstruction.py`) and confirmed the "supersede" rule handles same-date conflicts correctly
- Reviewed the validation rules in `src/validation.py` and confirmed rejected records are traceable
- Reviewed all schema constraints in `sql/schema.sql`
- Made final architectural decisions: targeted per-customer rebuild vs. incremental patching; TEXT run_id; pure classification layer

---

## AI Tool Details

- **Tool:** Google Antigravity (powered by Gemini)
- **Usage period:** During the 72-hour challenge window
- **Interaction mode:** Iterative back-and-forth; AI generated code, candidate reviewed, debugged, and approved
- **Prompt history:** Available on request; stored in the AI conversation session

---

## Candidate's Own Contributions

- Designed the three-layer architecture (event store + SCD dimension + audit layer)
- Identified edge cases: late-arriving events, same-timestamp conflicts, idempotent reruns
- Decided data model trade-offs (see `docs/design_tradeoffs.md`)
- Wrote the business rules and acceptance criteria interpretation
- Ran the full test suite and verified results end-to-end
- Configured the Docker PostgreSQL environment
- Managed the git repository and submission
