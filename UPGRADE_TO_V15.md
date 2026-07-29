# Upgrade to Product Hunter Pro v15

## Recommended search setup

v15 uses **SearXNG as the primary web-search provider**. Brave is not required. SerpApi remains optional only for Google Shopping, Google Maps, and Google Lens.

Add this to Streamlit Secrets:

```toml
SEARXNG_URL = "https://your-searxng-domain.example.com"
SEARCH_PROVIDER_ORDER = "searxng,serpapi"

# Optional specialized compatibility
SERPAPI_API_KEY = ""

OPENAI_API_KEY = "your-openai-key"
APP_PASSWORD = "your-app-password"
```

## SearXNG server requirement

The SearXNG instance must permit JSON output. In `settings.yml`, ensure:

```yaml
search:
  formats:
    - html
    - json
```

Restart SearXNG after changing its settings. In Product Hunter, use **Test SearXNG connection** in the sidebar.

## Search behavior

One product search now sends procurement-specific variants through SearXNG for:

- exact product/model
- official manufacturer pages
- technical PDFs and submittals
- distributors, quotes, pricing, and lead times
- discontinued, obsolete, superseded, and replacement references

The app merges, deduplicates, classifies, and ranks the results.
