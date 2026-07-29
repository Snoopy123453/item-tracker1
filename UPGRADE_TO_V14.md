# Upgrade to Product Hunter Pro v14

## What changed

v14 replaces the single-provider web-search dependency with a modular provider layer:

1. **SearXNG** — recommended primary provider. Self-hosted, open source, and no per-query API charge.
2. **Brave Search API** — reliable hosted fallback with an independent web index.
3. **SerpApi** — optional compatibility provider for Google Shopping, Maps, and Lens.

OmniSearch runs every enabled provider, normalizes the responses, removes duplicate URLs, classifies sources, and ranks the merged evidence. If one provider fails, the others continue.

## Recommended Streamlit secrets

```toml
SEARXNG_URL = "https://your-searxng-instance.example.com"
BRAVE_SEARCH_API_KEY = "your-brave-key"
SERPAPI_API_KEY = ""
SEARCH_PROVIDER_ORDER = "searxng,brave,serpapi"

OPENAI_API_KEY = "your-openai-key"
APP_PASSWORD = "your-private-password"
```

A SearXNG instance must have JSON output enabled. Public instances frequently disable JSON or rate-limit automated requests, so a private/self-hosted instance is recommended.

Without SerpApi, broad web, manufacturer, distributor, documentation, retailer-page, and legacy searches still work through SearXNG/Brave. Google Shopping's structured prices, Google Maps nearby-store records, and Google Lens remain disabled because those are provider-specific features.

## Deploy

Upload all files from this folder to the root of the GitHub repository, replace the previous version, commit, update Streamlit Secrets, and reboot the app.
