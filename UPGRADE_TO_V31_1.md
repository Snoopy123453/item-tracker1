# Product Hunter Pro v31.1 — Startup Crash Hotfix

## Fixed

- Corrected unescaped CSS braces in the enterprise ribbon and award-card styles.
- Prevented the theme renderer from interpreting CSS declarations as Python expressions during startup.
- Restored normal loading for all workspaces, including RFQ & Quote Center.
- Updated visible version labels to v31.1.
- Added a regression test for this startup failure.

## Deploy

Upload all files in this folder to the root of `item-tracker1`, replace the v31 files, commit, and reboot Streamlit.

No secret changes are required.
