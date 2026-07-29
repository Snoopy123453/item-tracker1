# Product Hunter Pro v25 — Readability and Accessibility Patch

This release focuses on consistent text contrast and a cleaner professional interface across light and dark modes.

## Improvements

- Rebuilt the light and dark color systems with separate tokens for normal, strong, muted, subtle, link, focus, border, and status text.
- Added a Standard/Large text-size control.
- Corrected mismatched colors in forms, dropdowns, tabs, alerts, buttons, metrics, tables, file uploaders, expanders, tooltips, cards, and empty states.
- Added clear keyboard-focus outlines and improved link visibility.
- Added readable status backgrounds for information, success, warning, and error messages.
- Improved sidebar contrast while keeping form inputs easy to read.
- Improved hover, selected-row, and disabled-control states.
- Added reduced-motion support for users who enable it in their operating system.
- Fixed legacy CSS variables in the resource-usage card that could render with incorrect colors.
- Updated interface labels to v25.

## Deployment

Upload every file inside `product_hunter_webapp_v25` to the root of the existing GitHub repository, replace older files, commit, and reboot Streamlit.

No secret values need to change.
