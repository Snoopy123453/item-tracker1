# Product Hunter Pro v18

This update fixes SearXNG searches that passed the connection test but returned zero results in Product Hunter.

## Fixes

- The SearXNG adapter now first uses the minimal working API request: `q` plus `format=json`.
- It no longer forces the generic `language=en` and SafeSearch parameters on the first request.
- If the first response is empty, it retries with `language=en-US` and SafeSearch disabled.
- Research concurrency is reduced for Render free instances to avoid overwhelming a waking service.
- Research provider diagnostics are now visible in the app when no unified results are returned.

## Update

Upload all files in this folder to the root of the existing Streamlit GitHub repository, replace the old files, commit, then reboot the Streamlit app.

Keep these Streamlit secrets:

```toml
SEARCH_PROVIDER_ORDER = "searxng"
SEARXNG_URL = "https://product-hunter-searxng-kvlv.onrender.com"
```
