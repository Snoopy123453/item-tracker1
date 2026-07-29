# Product Hunter Pro v16 — Dynamic Manufacturer Discovery

## Purpose

v16 removes the need for a fixed manufacturer list. A product can come from a manufacturer the app has never encountered before.

## Search process

1. SearXNG performs a broad product, document, supplier, and lifecycle search.
2. The app scores domains using exact-model evidence, repeated relevant results, brand/domain similarity, and technical-document evidence.
3. The strongest likely manufacturer domains are searched again with `site:` and PDF-focused queries.
4. Official-domain candidates are clearly marked as candidates until the exact model or technical document confirms them.
5. Distributor, retailer, legacy, and document results remain in the same OmniSearch table.

## Streamlit Secrets

```toml
SEARXNG_URL = "https://your-private-searxng-instance.example.com"
SEARCH_PROVIDER_ORDER = "searxng,serpapi"
SERPAPI_API_KEY = "" # optional
OPENAI_API_KEY = "your-openai-key"
APP_PASSWORD = "your-password"
```

## Safety behavior

The app does not blindly label every non-retailer site as official. Dynamically discovered domains are marked **Official-domain candidate — verify** unless stronger exact-model evidence is present.

## Updating

Upload all files from this folder to the root of the GitHub repository, replace previous files, commit, then reboot the Streamlit app.
