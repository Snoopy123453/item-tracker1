# Product Hunter Pro v26 — Stability and Commercial Readiness Patch

## Critical fix

The Procurement Control Center no longer crashes when an imported Excel/CSV file stores numbers or checkboxes as text. Offer tables are normalized before and after editing so Streamlit receives compatible text, numeric, Boolean, link, and status column types.

## Reliability improvements

- Missing offer columns receive safe defaults.
- Numeric fields tolerate blank or malformed imported values.
- Checkbox fields accept common values such as true/false, yes/no, and 1/0.
- Blank statuses default to **Needs review**.
- Exact-model and authorized-distributor fields now use explicit checkbox controls.
- Edited rows are normalized again before landed-cost calculations.

## Deployment

Upload all files in this folder to the root of the existing GitHub repository, replace older files, commit, and reboot Streamlit. No secret changes are required.
