# Product Hunter Pro v12 — OmniSearch

## What changed

Product Search now uses one **Search Everywhere (OmniSearch)** workflow. A single run searches and merges:

- Official manufacturer product pages
- Official catalogs and technical PDFs
- Authorized and major distributors
- Shopping and retailer listings
- Nearby supplier leads
- Spec sheets, submittals, manuals, warranties, parts, CAD, BIM, and Revit resources
- Legacy, discontinued, obsolete, superseded, replacement, and archive pages
- General web results that contain the exact model

## Unified ranking

Every source is normalized into the same result schema and receives:

- Product/model match score
- Source reliability score
- Overall evidence score
- Source classification
- Exact-model indicator
- Official-source indicator
- Distributor indicator
- Legacy/discontinued indicator
- Verification status and evidence explanation

Exact official manufacturer results rank first, followed by official documents, exact distributor listings, exact retailer listings, technical documents, local leads, and broader results.

## Unified app view

The new **OmniSearch — all sources** table supports filters for:

- Source type
- Exact-model results only
- Official sources only

The specialized Product Results, Nearby Stores, Spec Documents, and Manufacturer Sources sections remain available for detailed review.

## Excel

Exports now include an **OmniSearch Results** worksheet containing the merged and ranked evidence from every source.

## Deployment

1. Extract the v12 ZIP.
2. Upload all files and folders to the root of the existing GitHub repository.
3. Replace the previous files and commit the changes.
4. Reboot the Streamlit app.
5. Keep the existing OpenAI and SerpApi secrets.

No additional API key is required. OmniSearch uses the existing SerpApi integration.
