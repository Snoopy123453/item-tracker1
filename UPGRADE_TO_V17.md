# Product Hunter Pro v17 — AI Procurement Research Engine

## Main change

The Product Search workflow is now a procurement research workflow rather than a single generic web query.

For every product, SearXNG runs focused searches for:

- Exact product/model
- Official manufacturer and product pages
- Specification sheets and submittals
- Installation and O&M manuals
- Distributors, suppliers, pricing, and purchase pages
- Quotes, availability, stock, and lead-time references
- Discontinued, obsolete, superseded, and replacement products
- Warranty, parts, CAD, BIM, Revit, DWG, and catalogs in Deep mode

The engine runs queries concurrently, discovers likely manufacturer domains, then performs a second domain-restricted research pass.

## Streamlit Secrets

```toml
SEARXNG_URL = "https://product-hunter-searxng.onrender.com"
SEARCH_PROVIDER_ORDER = "searxng"
SERPAPI_API_KEY = ""
OPENAI_API_KEY = "your-openai-api-key"
OPENAI_MODEL = "your-supported-model"
APP_PASSWORD = "your-app-password"
```

## Update steps

1. Extract the v17 ZIP.
2. Upload everything inside the extracted folder to the root of your GitHub app repository.
3. Replace existing files and commit.
4. Confirm the Streamlit secrets above.
5. Reboot the Streamlit app.
6. Choose **Research Everywhere** and select Standard or Deep research.

## Important

SearXNG finds public web evidence. Firm quotes, account pricing, guaranteed inventory, and manufacturer lead times may still require an RFQ or vendor login.
