# Federal Bills Follow-Up

## After The Current 300-Row `summary_bullets` Backfill Finishes

Re-apply the federal-bills schema cleanup, because the running backfill started before the latest schema changes and may write an older in-memory dataframe back to the cache/Hugging Face.

Required fixes:

1. Rename `summary_threads` to `short_summary` if `summary_threads` comes back.
2. Drop `short_title` if it comes back.
3. Drop `summary_report` if it comes back.
4. Drop `pdf_url` if it comes back.
5. Re-drop rows where `text` is empty.
6. Rebuild bill-level vote aggregate columns from `.federal_votes_cache.parquet`.
7. Re-apply the preferred leading column order:
   - `date_last_action`
   - `date_introduced`
   - `title`
   - `text`
   - `policy_area`
   - `summary_bullets`
   - `short_summary`
   - `sponsor_full_name`
   - `sponsor_party`
   - `sponsor_state`
   - `num_cosponsors`
   - `chamber_of_origin`
   - all aggregated vote columns
8. Re-push `chrissoria/federal-bills-active` after the cleanup.

Current expected clean state:

- no `summary_threads`
- no `short_title`
- no `summary_report`
- no `pdf_url`
- no empty-`text` rows
- `short_summary` present
- `summary_bullets` preserved
