# Upgrade to Product Hunter Pro v8

Version 8 adds a Procurement Control Center while preserving Product Search, Project Intelligence, and Purchase Tracker.

## New controls

- Hard requirements, preferences, optional attributes, and ignore rules
- Side-by-side required-versus-found comparison
- Automatic rejection when a required attribute conflicts
- Package/component completeness checks
- Duplicate offer grouping by UPC, model, manufacturer, and normalized title
- Delivered-cost calculation including quantity, accessories, discounts, shipping, and estimated tax
- Missing-information review queue and pre-export data-health checks
- Vendor-name normalization and configurable vendor scorecards
- Document classification register
- Draft purchase-order worksheet
- Receiving log and audit history
- Procurement Control workbook and JSON backup

## Deploy

1. Extract the ZIP.
2. Upload everything inside `product_hunter_webapp_v8` to the root of the existing GitHub repository.
3. Replace older files and commit.
4. Reboot the Streamlit app.

Existing Streamlit secrets remain stored by Streamlit and do not need to be added again.
