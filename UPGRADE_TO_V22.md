# Product Hunter Pro v22 — Big Patch

## Major additions

- New Procurement Dashboard with research KPIs, recent activity, review status, and provider-health indicators.
- Persistent research-run telemetry in the SQLite Product Intelligence Database.
- Saved research views for source types, exact-model filters, official-source filters, and minimum evidence scores.
- Filtered CSV export from the unified research grid.
- Multi-source Evidence Comparison with side-by-side scores and JSON export.
- One-click reuse of recent dashboard searches.
- Knowledge snapshots now include research history and saved views.

## Deployment

Upload every file in this folder to the root of `item-tracker1`, replace the previous files, commit, and reboot Streamlit. Existing OpenAI and SearXNG secrets do not change.
